"""Windows vgamepad-based virtual Xbox 360 controller (stub).

This file is import-safe on Linux — the vgamepad import is guarded so that
importing this module on Linux does not raise ImportError.

TODO (full Windows implementation):
  1. Install ViGEm Bus Driver: https://github.com/ViGEm/ViGEmBus/releases
  2. Install vgamepad: pip install vgamepad
  3. Replace the no-op press/release stubs below with:
       self._gamepad = vgamepad.VX360Gamepad()
     and map Button enum values to vgamepad.XUSB_BUTTON constants, e.g.:
       Button.A     → vgamepad.XUSB_BUTTON.XUSB_GAMEPAD_A
       Button.LT    → gamepad.left_trigger(value=255) / gamepad.reset()
       (triggers require axis calls, not button press/release)
  4. Call self._gamepad.update() after each state change.
  5. Implement cleanup() to reset all buttons and triggers before deleting the device.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from controller import VirtualController
from parser import Axis, Button

if TYPE_CHECKING:
    from config import Config

log = logging.getLogger(__name__)


class WindowsController(VirtualController):
    """Stub Windows virtual controller — logs a warning and performs no input."""

    def __init__(self, config: Config) -> None:
        self._press_duration_ms = config.controller.press_duration_ms
        log.warning(
            "WindowsController is a stub. Button presses will be logged but not delivered. "
            "See controller/windows.py for implementation instructions."
        )

    async def press_down(self, button: Button) -> None:
        log.warning("[stub] press_down %s — no-op", button.value)

    async def release_button(self, button: Button) -> None:
        log.warning("[stub] release_button %s — no-op", button.value)

    async def set_axis(self, axis: Axis, value: int) -> None:
        log.warning("[stub] set_axis %s=%d — no-op", axis.value, value)

    async def cleanup(self) -> None:
        pass
