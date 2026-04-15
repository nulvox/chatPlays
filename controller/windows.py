"""Windows vgamepad-based virtual Xbox 360 controller.

Requires:
- vgamepad package   (pip install vgamepad)
- ViGEmBus driver    (https://github.com/ViGEm/ViGEmBus/releases)

The vgamepad import is guarded so this module remains import-safe on Linux.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from controller import VirtualController
from parser import Axis, Button, ChordStep

if TYPE_CHECKING:
    from config import Config

log = logging.getLogger(__name__)


def _scale_axis(value: int) -> int:
    """Convert percentage (-100..100) to raw stick axis value (-32768..32767)."""
    if value >= 0:
        return int(value * 32767 / 100)
    return int(value * 32768 / 100)


class WindowsController(VirtualController):
    """Virtual Xbox 360 gamepad via ViGEmBus + vgamepad."""

    def __init__(self, config: Config) -> None:
        self._press_duration_ms = config.controller.press_duration_ms

        try:
            import vgamepad
        except ImportError as exc:
            raise SystemExit(
                "vgamepad is not installed. Install it with:\n"
                "  pip install vgamepad\n"
                "You also need the ViGEmBus driver:\n"
                "  https://github.com/ViGEm/ViGEmBus/releases"
            ) from exc

        try:
            self._pad = vgamepad.VX360Gamepad()
        except Exception as exc:
            raise SystemExit(
                "Failed to create virtual gamepad. Is ViGEmBus installed and running?\n"
                "  Download: https://github.com/ViGEm/ViGEmBus/releases\n"
                "  Check:    sc query ViGEmBus\n"
                f"  Error:    {exc}"
            ) from exc

        # Button → XUSB_BUTTON constant (for press_button / release_button)
        xb = vgamepad.XUSB_BUTTON
        self._button_map: dict[Button, int] = {
            Button.A: xb.XUSB_GAMEPAD_A,
            Button.B: xb.XUSB_GAMEPAD_B,
            Button.X: xb.XUSB_GAMEPAD_X,
            Button.Y: xb.XUSB_GAMEPAD_Y,
            Button.LB: xb.XUSB_GAMEPAD_LEFT_SHOULDER,
            Button.RB: xb.XUSB_GAMEPAD_RIGHT_SHOULDER,
            Button.START: xb.XUSB_GAMEPAD_START,
            Button.BACK: xb.XUSB_GAMEPAD_BACK,
            Button.GUIDE: xb.XUSB_GAMEPAD_GUIDE,
            Button.LS: xb.XUSB_GAMEPAD_LEFT_THUMB,
            Button.RS: xb.XUSB_GAMEPAD_RIGHT_THUMB,
            Button.UP: xb.XUSB_GAMEPAD_DPAD_UP,
            Button.DOWN: xb.XUSB_GAMEPAD_DPAD_DOWN,
            Button.LEFT: xb.XUSB_GAMEPAD_DPAD_LEFT,
            Button.RIGHT: xb.XUSB_GAMEPAD_DPAD_RIGHT,
        }

        # Triggers use a separate axis path, not press_button
        self._trigger_buttons: set[Button] = {Button.LT, Button.RT}

        # Track raw axis state so setting one axis of a pair doesn't clobber
        # the other (e.g. setting LX preserves the current LY value).
        self._axis_raw: dict[Axis, int] = {
            Axis.LX: 0,
            Axis.LY: 0,
            Axis.RX: 0,
            Axis.RY: 0,
        }

        log.info("vgamepad device created: VX360Gamepad")

    # ── Abstract primitive implementations ────────────────────────────────────

    async def press_down(self, button: Button) -> None:
        if button == Button.LT:
            log.debug("emit trigger press: LT value=255")
            self._pad.left_trigger(value=255)
            self._pad.update()
        elif button == Button.RT:
            log.debug("emit trigger press: RT value=255")
            self._pad.right_trigger(value=255)
            self._pad.update()
        elif button in self._button_map:
            log.debug("emit button press: %s", button)
            self._pad.press_button(button=self._button_map[button])
            self._pad.update()
        else:
            log.warning("No vgamepad mapping for button %s", button)

    async def release_button(self, button: Button) -> None:
        if button == Button.LT:
            log.debug("emit trigger release: LT value=0")
            self._pad.left_trigger(value=0)
            self._pad.update()
        elif button == Button.RT:
            log.debug("emit trigger release: RT value=0")
            self._pad.right_trigger(value=0)
            self._pad.update()
        elif button in self._button_map:
            log.debug("emit button release: %s", button)
            self._pad.release_button(button=self._button_map[button])
            self._pad.update()

    async def set_axis(self, axis: Axis, value: int) -> None:
        raw = _scale_axis(value)
        log.debug("emit axis: %s raw=%d", axis, raw)
        if axis not in self._axis_raw:
            log.warning("No vgamepad mapping for axis %s", axis)
            return
        self._axis_raw[axis] = raw
        if axis in (Axis.LX, Axis.LY):
            self._pad.left_joystick(
                x_value=self._axis_raw[Axis.LX],
                y_value=self._axis_raw[Axis.LY],
            )
        else:
            self._pad.right_joystick(
                x_value=self._axis_raw[Axis.RX],
                y_value=self._axis_raw[Axis.RY],
            )
        self._pad.update()

    # ── Chord execution (override to handle hold_ms fallback) ─────────────

    async def _execute_chord(self, chord: ChordStep) -> None:
        """Press all buttons / set all axes, hold, then release.

        Extends the base implementation with two behaviours required by the spec:
        - ``hold_ms == 0`` on a button falls back to ``config.press_duration_ms``.
        - An axis-only chord (no buttons) sleeps for ``config.press_duration_ms``.
        """
        # Set axes
        for ai in chord.axes:
            await self.set_axis(ai.axis, ai.value)

        # Press all buttons down
        for btn in chord.buttons:
            await self.press_down(btn.button)

        if chord.buttons:
            # Staggered release: release each button when its hold_ms elapses.
            # A hold_ms of 0 means "use config default".
            def _hold(btn_hold: int) -> int:
                return btn_hold if btn_hold > 0 else self._press_duration_ms

            sorted_btns = sorted(chord.buttons, key=lambda b: _hold(b.hold_ms))
            elapsed = 0
            for btn in sorted_btns:
                wait = _hold(btn.hold_ms) - elapsed
                if wait > 0:
                    await asyncio.sleep(wait / 1000.0)
                    elapsed += wait
                await self.release_button(btn.button)
        else:
            # Axis-only chord: hold for the config default duration.
            await asyncio.sleep(self._press_duration_ms / 1000.0)

        # Reset axes to centre
        for ai in chord.axes:
            await self.set_axis(ai.axis, 0)

    async def cleanup(self) -> None:
        """Reset and release the virtual gamepad."""
        if hasattr(self, "_pad") and self._pad is not None:
            self._pad.reset()
            self._pad.update()
            del self._pad
            self._pad = None  # type: ignore[assignment,unused-ignore]
            log.info("vgamepad device destroyed")
