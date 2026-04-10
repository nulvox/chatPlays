"""Tests for queue_engine.py."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal
from unittest.mock import AsyncMock

import pytest

from parser import Button, ButtonInput, ChordStep, Sequence
from queue_engine import QueueEngine

# ── Minimal config stubs ───────────────────────────────────────────────────────


@dataclass
class _DiscordCfg:
    command_prefix: str = "!"
    channel_id: int = 0
    token: str = "tok"


@dataclass
class _QueueCfg:
    mode: Literal["fifo", "vote"] = "fifo"
    vote_window_seconds: float = 0.2  # short for tests
    fifo_execute_interval: float = 0.05
    max_depth: int = 5


@dataclass
class _RLCfg:
    cooldown_seconds: float = 0.0
    max_per_window: int = 100


@dataclass
class _CtrlCfg:
    press_duration_ms: int = 50
    platform: str = "auto"
    max_hold_ms: int = 5000
    max_sequence_steps: int = 20
    max_total_duration_ms: int = 10000


@dataclass
class _Cfg:
    discord: _DiscordCfg = None  # type: ignore
    queue: _QueueCfg = None  # type: ignore
    rate_limit: _RLCfg = None  # type: ignore
    controller: _CtrlCfg = None  # type: ignore

    def __post_init__(self) -> None:
        if self.discord is None:
            self.discord = _DiscordCfg()
        if self.queue is None:
            self.queue = _QueueCfg()
        if self.rate_limit is None:
            self.rate_limit = _RLCfg()
        if self.controller is None:
            self.controller = _CtrlCfg()


def make_engine(
    mode: Literal["fifo", "vote"] = "fifo", max_depth: int = 5
) -> tuple[QueueEngine, AsyncMock]:
    cfg = _Cfg(queue=_QueueCfg(mode=mode, max_depth=max_depth))
    mock_ctrl = AsyncMock()
    mock_ctrl.execute_sequence = AsyncMock()
    mock_ctrl.press_down = AsyncMock()
    mock_ctrl.release_button = AsyncMock()
    mock_ctrl.set_axis = AsyncMock()
    mock_ctrl.cleanup = AsyncMock()
    engine = QueueEngine(cfg, mock_ctrl)  # type: ignore
    return engine, mock_ctrl


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestFifoMode:
    @pytest.mark.asyncio
    async def test_command_executes(self):
        engine, ctrl = make_engine("fifo")
        await engine.start()
        await engine.on_command("user1", "!a")
        await asyncio.sleep(0.2)  # let dispatch loop run
        await engine.stop()
        ctrl.execute_sequence.assert_awaited()

    @pytest.mark.asyncio
    async def test_queue_overflow_drops_oldest(self):
        engine, ctrl = make_engine("fifo", max_depth=2)
        # Pause so commands accumulate
        engine.pause()
        await engine.start()
        await engine.on_command("u", "!a")
        await engine.on_command("u", "!b")
        await engine.on_command("u", "!x")  # should overflow, drop oldest
        status = engine.get_status()
        assert status["queue_depth"] == 2
        await engine.stop()

    @pytest.mark.asyncio
    async def test_pause_halts_execution(self):
        engine, ctrl = make_engine("fifo")
        await engine.start()
        engine.pause()
        await engine.on_command("u", "!a")
        await asyncio.sleep(0.15)
        assert ctrl.execute_sequence.await_count == 0
        await engine.stop()

    @pytest.mark.asyncio
    async def test_resume_after_pause(self):
        engine, ctrl = make_engine("fifo")
        await engine.start()
        engine.pause()
        await engine.on_command("u", "!a")
        await asyncio.sleep(0.05)
        engine.resume()
        await asyncio.sleep(0.2)
        await engine.stop()
        ctrl.execute_sequence.assert_awaited()


class TestVoteMode:
    @pytest.mark.asyncio
    async def test_winner_executes_once(self):
        engine, ctrl = make_engine("vote")
        await engine.start()
        # 2 votes for A, 1 for B
        await engine.on_command("u1", "!a")
        await engine.on_command("u2", "!a")
        await engine.on_command("u3", "!b")
        # Wait for window to expire and execute
        await asyncio.sleep(0.5)
        await engine.stop()
        assert ctrl.execute_sequence.await_count == 1
        call_arg: Sequence = ctrl.execute_sequence.call_args[0][0]
        step = call_arg.steps[0]
        assert isinstance(step, ChordStep)
        assert step.buttons[0].button == Button.A

    @pytest.mark.asyncio
    async def test_tie_broken_by_earliest(self):
        engine, ctrl = make_engine("vote")
        await engine.start()
        # 1 vote each — A submitted first, should win
        await engine.on_command("u1", "!a")
        await asyncio.sleep(0.01)
        await engine.on_command("u2", "!b")
        await asyncio.sleep(0.5)
        await engine.stop()
        call_arg: Sequence = ctrl.execute_sequence.call_args[0][0]
        step = call_arg.steps[0]
        assert isinstance(step, ChordStep)
        assert step.buttons[0].button == Button.A


class TestModeSwitching:
    @pytest.mark.asyncio
    async def test_switch_mode(self):
        engine, _ = make_engine("fifo")
        await engine.start()
        assert engine.get_status()["mode"] == "fifo"
        engine.set_mode("vote")
        assert engine.get_status()["mode"] == "vote"
        await engine.stop()

    @pytest.mark.asyncio
    async def test_switch_drains_queue(self):
        engine, ctrl = make_engine("fifo")
        engine.pause()
        await engine.start()
        await engine.on_command("u", "!a")
        assert engine.get_status()["queue_depth"] == 1
        engine.set_mode("vote")
        assert engine.get_status()["queue_depth"] == 0
        await engine.stop()


class TestTallyVotes:
    def _seq(self, button: Button, hold: int = 100) -> Sequence:
        step = ChordStep(buttons=(ButtonInput(button, hold),), axes=())
        canonical = f"{button.value}:{hold}"
        return Sequence(steps=(step,), canonical=canonical)

    def test_single_entry(self):
        buf = [(0.0, self._seq(Button.A))]
        result = QueueEngine._tally_votes(buf)
        assert result is not None
        step = result.steps[0]
        assert isinstance(step, ChordStep)
        assert step.buttons[0].button == Button.A

    def test_majority_wins(self):
        buf = [
            (0.0, self._seq(Button.A)),
            (0.1, self._seq(Button.B)),
            (0.2, self._seq(Button.A)),
        ]
        result = QueueEngine._tally_votes(buf)
        assert result is not None
        step = result.steps[0]
        assert isinstance(step, ChordStep)
        assert step.buttons[0].button == Button.A

    def test_empty_buffer(self):
        result = QueueEngine._tally_votes([])
        assert result is None

    def test_sequence_commands_grouped(self):
        """Identical sequence commands should be grouped together in votes."""
        seq1 = Sequence(
            steps=(
                ChordStep(buttons=(ButtonInput(Button.DOWN, 100),), axes=()),
                ChordStep(buttons=(ButtonInput(Button.RIGHT, 100),), axes=()),
                ChordStep(buttons=(ButtonInput(Button.A, 100),), axes=()),
            ),
            canonical="a:100 down:100 right:100",
        )
        seq2 = Sequence(
            steps=(
                ChordStep(buttons=(ButtonInput(Button.DOWN, 100),), axes=()),
                ChordStep(buttons=(ButtonInput(Button.RIGHT, 100),), axes=()),
                ChordStep(buttons=(ButtonInput(Button.A, 100),), axes=()),
            ),
            canonical="a:100 down:100 right:100",  # same canonical
        )
        seq_other = self._seq(Button.B)

        buf = [(0.0, seq1), (0.1, seq2), (0.2, seq_other)]
        result = QueueEngine._tally_votes(buf)
        assert result is not None
        assert result.canonical == seq1.canonical
