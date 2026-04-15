"""Tests for controller/windows.py — WindowsController (vgamepad + ViGEmBus).

These tests run inside a provisioned Windows VM. They exercise the controller
directly with hand-constructed Sequence objects and parser-produced sequences.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

import pytest

from parser import (
    Axis,
    AxisInput,
    Button,
    ButtonInput,
    ChordStep,
    Sequence,
    WaitStep,
    parse_command,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _seq_button(button: Button, hold_ms: int = 100) -> Sequence:
    """Build a single-button Sequence."""
    step = ChordStep(buttons=(ButtonInput(button, hold_ms),), axes=())
    return Sequence(steps=(step,), canonical=f"{button.value}:{hold_ms}")


def _seq_chord(buttons: list[tuple[Button, int]], axes: list[tuple[Axis, int]] = ()) -> Sequence:
    """Build a chord Sequence with multiple buttons and optional axes."""
    btn_inputs = tuple(ButtonInput(b, h) for b, h in buttons)
    axis_inputs = tuple(AxisInput(a, v) for a, v in axes)
    step = ChordStep(buttons=btn_inputs, axes=axis_inputs)
    parts = [f"{b.value}:{h}" for b, h in buttons]
    parts += [f"{a.value}:{v}" for a, v in axes]
    return Sequence(steps=(step,), canonical="+".join(parts))


def _scale_axis(value: int) -> int:
    """Mirror the controller's axis scaling."""
    if value >= 0:
        return int(value * 32767 / 100)
    return int(value * 32768 / 100)


# ── Device lifecycle ─────────────────────────────────────────────────────────


class TestDeviceLifecycle:
    def test_create_device(self, controller):
        import vgamepad

        assert hasattr(controller, "_pad")
        assert isinstance(controller._pad, vgamepad.VX360Gamepad)

    @pytest.mark.asyncio
    async def test_cleanup_destroys_device(self, controller):
        await controller.cleanup()
        assert controller._pad is None
        # Second cleanup is a safe no-op
        await controller.cleanup()

    def test_create_without_vigembus(self, monkeypatch, config):
        import controller.windows as win_mod

        original_import = (
            __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__
        )

        def fake_import(name, *args, **kwargs):
            if name == "vgamepad":
                raise ImportError("mocked")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", fake_import)
        with pytest.raises(SystemExit, match="vgamepad"):
            from importlib import reload

            reload(win_mod)
            win_mod.WindowsController(config)


# ── Button mapping completeness ──────────────────────────────────────────────


class TestButtonMapping:
    def test_all_buttons_mapped(self, controller):
        trigger_buttons = {Button.LT, Button.RT}
        for button in Button:
            assert button in controller._button_map or button in trigger_buttons, (
                f"Button {button} has no mapping"
            )

    def test_no_duplicate_mappings(self, controller):
        values = list(controller._button_map.values())
        assert len(values) == len(set(values)), "Duplicate button mappings found"


# ── Single-step execution ────────────────────────────────────────────────────


class TestSingleButton:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("button", [Button.A, Button.B, Button.X, Button.Y])
    async def test_face_button_press(self, controller, button):
        seq = _seq_button(button)
        await controller.execute_sequence(seq)
        # After execution, button should be released (report clean)
        report = controller._pad.report
        assert report.wButtons == 0

    @pytest.mark.asyncio
    async def test_trigger_lt_press(self, controller):
        seq = _seq_button(Button.LT)
        await controller.execute_sequence(seq)
        report = controller._pad.report
        assert report.bLeftTrigger == 0

    @pytest.mark.asyncio
    async def test_trigger_rt_press(self, controller):
        seq = _seq_button(Button.RT)
        await controller.execute_sequence(seq)
        report = controller._pad.report
        assert report.bRightTrigger == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "button",
        [Button.UP, Button.DOWN, Button.LEFT, Button.RIGHT],
    )
    async def test_dpad_press(self, controller, button):
        seq = _seq_button(button)
        await controller.execute_sequence(seq)
        report = controller._pad.report
        assert report.wButtons == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "button",
        [Button.START, Button.BACK, Button.GUIDE, Button.LS, Button.RS],
    )
    async def test_meta_buttons(self, controller, button):
        seq = _seq_button(button)
        await controller.execute_sequence(seq)
        report = controller._pad.report
        assert report.wButtons == 0


class TestChords:
    @pytest.mark.asyncio
    async def test_chord_multiple_buttons(self, controller):
        seq = _seq_chord([(Button.A, 100), (Button.B, 100)])
        await controller.execute_sequence(seq)
        report = controller._pad.report
        assert report.wButtons == 0

    @pytest.mark.asyncio
    async def test_chord_buttons_and_axes(self, controller):
        seq = _seq_chord(
            [(Button.A, 100)],
            axes=[(Axis.LX, 100)],
        )
        await controller.execute_sequence(seq)
        report = controller._pad.report
        assert report.wButtons == 0
        assert report.sThumbLX == 0


class TestAxisScaling:
    @pytest.mark.asyncio
    async def test_axis_positive_max(self, controller):
        assert _scale_axis(100) == 32767

    @pytest.mark.asyncio
    async def test_axis_negative_max(self, controller):
        assert _scale_axis(-100) == -32768

    @pytest.mark.asyncio
    async def test_axis_zero(self, controller):
        assert _scale_axis(0) == 0

    @pytest.mark.asyncio
    async def test_axes_reset_after_step(self, controller):
        step = ChordStep(
            buttons=(ButtonInput(Button.A, 100),),
            axes=(AxisInput(Axis.LX, 70),),
        )
        seq = Sequence(steps=(step,), canonical="a:100+lx:70")
        await controller.execute_sequence(seq)
        report = controller._pad.report
        assert report.sThumbLX == 0
        assert report.sThumbLY == 0
        assert report.sThumbRX == 0
        assert report.sThumbRY == 0

    @pytest.mark.asyncio
    async def test_axis_preserves_paired_value(self, controller):
        """Setting LX must not clobber the current LY value."""
        # Set LY first
        await controller.set_axis(Axis.LY, 50)
        report = controller._pad.report
        assert report.sThumbLY == _scale_axis(50)

        # Now set LX — LY should be preserved
        await controller.set_axis(Axis.LX, 70)
        report = controller._pad.report
        assert report.sThumbLX == _scale_axis(70)
        assert report.sThumbLY == _scale_axis(50)

    @pytest.mark.asyncio
    async def test_axis_preserves_right_stick(self, controller):
        """Setting RY must not clobber the current RX value."""
        await controller.set_axis(Axis.RX, -80)
        await controller.set_axis(Axis.RY, 60)
        report = controller._pad.report
        assert report.sThumbRX == _scale_axis(-80)
        assert report.sThumbRY == _scale_axis(60)


# ── Multi-step execution ─────────────────────────────────────────────────────


class TestMultiStep:
    @pytest.mark.asyncio
    async def test_two_step_sequence(self, controller):
        step_a = ChordStep(buttons=(ButtonInput(Button.A, 100),), axes=())
        step_b = ChordStep(buttons=(ButtonInput(Button.B, 100),), axes=())
        seq = Sequence(steps=(step_a, step_b), canonical="a:100 b:100")
        await controller.execute_sequence(seq)
        report = controller._pad.report
        assert report.wButtons == 0

    @pytest.mark.asyncio
    async def test_sequence_with_wait(self, controller):
        hold = 100
        wait = 100
        step_a = ChordStep(buttons=(ButtonInput(Button.A, hold),), axes=())
        step_w = WaitStep(wait_ms=wait)
        step_b = ChordStep(buttons=(ButtonInput(Button.B, hold),), axes=())
        seq = Sequence(steps=(step_a, step_w, step_b), canonical="a:100 ~100 b:100")

        start = time.monotonic()
        await controller.execute_sequence(seq)
        elapsed_ms = (time.monotonic() - start) * 1000

        expected_ms = hold + wait + hold  # 300ms
        assert elapsed_ms >= expected_ms - 50
        assert elapsed_ms <= expected_ms + 150

    @pytest.mark.asyncio
    async def test_sequence_with_chord_timing(self, controller):
        step = ChordStep(
            buttons=(
                ButtonInput(Button.A, 50),
                ButtonInput(Button.B, 200),
            ),
            axes=(),
        )
        seq = Sequence(steps=(step,), canonical="a:50+b:200")

        start = time.monotonic()
        await controller.execute_sequence(seq)
        elapsed_ms = (time.monotonic() - start) * 1000

        # Should take ~200ms (longest hold wins)
        assert elapsed_ms >= 150
        assert elapsed_ms <= 350


# ── Timing ───────────────────────────────────────────────────────────────────


@dataclass
class _CtrlCfg200:
    press_duration_ms: int = 200
    platform: Literal["auto", "linux", "windows"] = "windows"
    device_index: int = 0
    max_hold_ms: int = 5000
    max_sequence_steps: int = 20
    max_total_duration_ms: int = 10000


@dataclass
class _DiscordCfg:
    command_prefix: str = "!"
    channel_id: int = 0
    token: str = "tok"


@dataclass
class _QueueCfg:
    mode: Literal["fifo", "vote"] = "fifo"
    vote_window_seconds: float = 5.0
    fifo_execute_interval: float = 0.1
    max_depth: int = 50


@dataclass
class _RLCfg:
    cooldown_seconds: float = 1.0
    max_per_window: int = 3
    global_max_per_minute: int = 60


@dataclass
class _Cfg200:
    discord: _DiscordCfg = None  # type: ignore
    queue: _QueueCfg = None  # type: ignore
    rate_limit: _RLCfg = None  # type: ignore
    controller: _CtrlCfg200 = None  # type: ignore

    def __post_init__(self) -> None:
        if self.discord is None:
            self.discord = _DiscordCfg()
        if self.queue is None:
            self.queue = _QueueCfg()
        if self.rate_limit is None:
            self.rate_limit = _RLCfg()
        if self.controller is None:
            self.controller = _CtrlCfg200()


class TestTiming:
    @pytest.mark.asyncio
    async def test_uses_config_default_duration(self):
        """hold_ms=0 falls back to config.press_duration_ms (200ms)."""
        from controller.windows import WindowsController

        cfg = _Cfg200()
        ctrl = WindowsController(cfg)
        try:
            step = ChordStep(buttons=(ButtonInput(Button.A, 0),), axes=())
            seq = Sequence(steps=(step,), canonical="a:0")
            start = time.monotonic()
            await ctrl.execute_sequence(seq)
            elapsed_ms = (time.monotonic() - start) * 1000
            assert elapsed_ms >= 150
            assert elapsed_ms <= 350
        finally:
            await ctrl.cleanup()

    @pytest.mark.asyncio
    async def test_uses_explicit_duration(self, controller):
        seq = _seq_button(Button.A, hold_ms=150)
        start = time.monotonic()
        await controller.execute_sequence(seq)
        elapsed_ms = (time.monotonic() - start) * 1000
        assert elapsed_ms >= 100
        assert elapsed_ms <= 300

    @pytest.mark.asyncio
    async def test_axis_only_chord_uses_config_duration(self):
        """A chord with axes but no buttons sleeps for press_duration_ms."""
        from controller.windows import WindowsController

        cfg = _Cfg200()
        ctrl = WindowsController(cfg)
        try:
            step = ChordStep(buttons=(), axes=(AxisInput(Axis.LX, 70),))
            seq = Sequence(steps=(step,), canonical="lx:70")
            start = time.monotonic()
            await ctrl.execute_sequence(seq)
            elapsed_ms = (time.monotonic() - start) * 1000
            # Should take ~200ms (config default)
            assert elapsed_ms >= 150
            assert elapsed_ms <= 350
            # Axes should be reset after
            report = ctrl._pad.report
            assert report.sThumbLX == 0
        finally:
            await ctrl.cleanup()


# ── Integration with parser ──────────────────────────────────────────────────


class TestParserIntegration:
    @pytest.mark.asyncio
    async def test_parsed_command_through_controller(self, controller):
        seq = parse_command("!a+b ~100 down", "!", 100)
        assert seq is not None
        await controller.execute_sequence(seq)

    @pytest.mark.asyncio
    async def test_parsed_chord_with_axis(self, controller):
        seq = parse_command("!lx:70+a", "!", 100)
        assert seq is not None
        await controller.execute_sequence(seq)
        report = controller._pad.report
        assert report.sThumbLX == 0

    @pytest.mark.asyncio
    async def test_parsed_numpad_notation(self, controller):
        seq = parse_command("!2 3 6 a", "!", 100)
        assert seq is not None
        assert len(seq.steps) == 4
        await controller.execute_sequence(seq)


# ── Edge cases ───────────────────────────────────────────────────────────────


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_cleanup_without_execution(self, config):
        from controller.windows import WindowsController

        ctrl = WindowsController(config)
        await ctrl.cleanup()

    @pytest.mark.asyncio
    async def test_rapid_sequential_commands(self, controller):
        for _ in range(10):
            seq = _seq_button(Button.A, hold_ms=10)
            await controller.execute_sequence(seq)
        report = controller._pad.report
        assert report.wButtons == 0

    @pytest.mark.asyncio
    async def test_empty_axes_chord(self, controller):
        step = ChordStep(
            buttons=(ButtonInput(Button.A, 100), ButtonInput(Button.B, 100)),
            axes=(),
        )
        seq = Sequence(steps=(step,), canonical="a:100+b:100")
        await controller.execute_sequence(seq)
        report = controller._pad.report
        assert report.sThumbLX == 0
        assert report.sThumbLY == 0
        assert report.sThumbRX == 0
        assert report.sThumbRY == 0
