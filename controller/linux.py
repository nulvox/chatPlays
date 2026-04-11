"""Linux uinput-based virtual Xbox 360 controller.

Requires:
- python-uinput package  (pip install python-uinput)
- uinput kernel module   (modprobe uinput)
- User in 'input' group  (sudo usermod -aG input $USER, then re-login)

The device presents with Xbox 360 USB vendor/product IDs (045e:028e) so Steam
recognises it as a native controller without any special Steam Input profile.

D-pad note: on a real Xbox 360 controller the d-pad is exposed as two HAT axes
(ABS_HAT0X / ABS_HAT0Y), not as buttons. We replicate that here so Steam
recognises it correctly.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from controller import VirtualController
from parser import Axis, Button

if TYPE_CHECKING:
    from config import Config

log = logging.getLogger(__name__)

# Xbox 360 controller USB IDs
_VENDOR_ID = 0x045E
_PRODUCT_ID = 0x028E
_BUS_USB = 0x03


@dataclass(frozen=True)
class _AxisPress:
    """D-pad press encoded as an absolute axis event."""

    axis: tuple[int, int]  # e.g. uinput.ABS_HAT0X
    value: int  # -1, 0, or 1


# Built lazily after uinput is imported
_BUTTON_MAP: dict[Button, tuple[int, int]] = {}
_DPAD_MAP: dict[Button, _AxisPress] = {}
_STICK_AXIS_MAP: dict[Axis, tuple[int, int]] = {}


def _build_maps() -> tuple[
    dict[Button, tuple[int, int]], dict[Button, _AxisPress], dict[Axis, tuple[int, int]]
]:
    import uinput

    buttons = {
        Button.A: uinput.BTN_A,
        Button.B: uinput.BTN_B,
        Button.X: uinput.BTN_X,
        Button.Y: uinput.BTN_Y,
        Button.LB: uinput.BTN_TL,
        Button.RB: uinput.BTN_TR,
        Button.LT: uinput.BTN_TL2,
        Button.RT: uinput.BTN_TR2,
        Button.START: uinput.BTN_START,
        Button.BACK: uinput.BTN_SELECT,
        Button.GUIDE: uinput.BTN_MODE,
        Button.LS: uinput.BTN_THUMBL,
        Button.RS: uinput.BTN_THUMBR,
    }

    # D-pad is ABS_HAT0X (left/right) and ABS_HAT0Y (up/down).
    # Y axis: -1 = up, +1 = down  (standard Linux HAT convention)
    dpad = {
        Button.UP: _AxisPress(uinput.ABS_HAT0Y, -1),
        Button.DOWN: _AxisPress(uinput.ABS_HAT0Y, 1),
        Button.LEFT: _AxisPress(uinput.ABS_HAT0X, -1),
        Button.RIGHT: _AxisPress(uinput.ABS_HAT0X, 1),
    }

    stick_axes = {
        Axis.LX: uinput.ABS_X,
        Axis.LY: uinput.ABS_Y,
        Axis.RX: uinput.ABS_RX,
        Axis.RY: uinput.ABS_RY,
    }

    return buttons, dpad, stick_axes


def _scale_axis(value: int) -> int:
    """Convert percentage (-100..100) to raw stick axis value (-32768..32767)."""
    if value >= 0:
        return int(value * 32767 / 100)
    return int(value * 32768 / 100)


class LinuxController(VirtualController):
    """Virtual Xbox 360 gamepad via /dev/uinput."""

    def __init__(self, config: Config) -> None:
        self._press_duration_ms = config.controller.press_duration_ms
        self._device_index = config.controller.device_index
        self._device: object | None = None
        self._button_map: dict[Button, tuple[int, int]] = {}
        self._dpad_map: dict[Button, _AxisPress] = {}
        self._stick_axis_map: dict[Axis, tuple[int, int]] = {}
        self._ensure_device()

    def _ensure_device(self) -> None:
        """Lazily create the uinput device on first use."""
        if self._device is not None:
            return

        try:
            import uinput
        except ImportError as exc:
            raise RuntimeError(
                "python-uinput is not installed. Install it with: pip install python-uinput"
            ) from exc

        self._button_map, self._dpad_map, self._stick_axis_map = _build_maps()

        # Register the full Xbox 360 axis profile so Steam recognises the device
        # correctly. Sticks and triggers are registered but held at zero — only
        # the HAT axes are driven by d-pad commands.
        stick_spec = (-32768, 32767, 16, 128)  # (min, max, fuzz, flat)
        trigger_spec = (0, 255, 0, 0)
        hat_spec = (-1, 1, 0, 0)
        events = list(self._button_map.values()) + [
            uinput.ABS_X + stick_spec,
            uinput.ABS_Y + stick_spec,
            uinput.ABS_Z + trigger_spec,
            uinput.ABS_RX + stick_spec,
            uinput.ABS_RY + stick_spec,
            uinput.ABS_RZ + trigger_spec,
            uinput.ABS_HAT0X + hat_spec,
            uinput.ABS_HAT0Y + hat_spec,
        ]

        # Use device_index to differentiate multiple instances. Index 0 keeps
        # the standard name/version so a single-instance setup is unchanged.
        if self._device_index:
            device_name = f"Microsoft X-Box 360 pad #{self._device_index + 1}"
            device_version = 0x0114 + self._device_index
        else:
            device_name = "Microsoft X-Box 360 pad"
            device_version = 0x0114

        try:
            self._device = uinput.Device(
                events,
                name=device_name,
                bustype=_BUS_USB,
                vendor=_VENDOR_ID,
                product=_PRODUCT_ID,
                version=device_version,
            )
        except Exception as exc:
            raise RuntimeError(
                "Failed to create uinput device. Common causes:\n"
                "  • uinput module not loaded: run 'sudo modprobe uinput'\n"
                "  • User not in 'input' group: run 'sudo usermod -aG input $USER' "
                "and log out/in\n"
                f"  • Original error: {exc}"
            ) from exc

        log.info(
            "uinput device created: Microsoft X-Box 360 pad (%04x:%04x)",
            _VENDOR_ID,
            _PRODUCT_ID,
        )

    # ── Abstract primitive implementations ────────────────────────────────────

    async def press_down(self, button: Button) -> None:
        self._ensure_device()
        assert self._device is not None
        if button in self._dpad_map:
            ap = self._dpad_map[button]
            log.debug("emit dpad press: axis=%s value=%d", ap.axis, ap.value)
            await asyncio.to_thread(self._device.emit, ap.axis, ap.value)  # type: ignore
        elif button in self._button_map:
            event = self._button_map[button]
            log.debug("emit button press: %s event=%s", button, event)
            await asyncio.to_thread(self._device.emit, event, 1)  # type: ignore
        else:
            log.warning("No uinput mapping for button %s", button)

    async def release_button(self, button: Button) -> None:
        self._ensure_device()
        assert self._device is not None
        if button in self._dpad_map:
            ap = self._dpad_map[button]
            log.debug("emit dpad release: axis=%s value=0", ap.axis)
            await asyncio.to_thread(self._device.emit, ap.axis, 0)  # type: ignore
        elif button in self._button_map:
            event = self._button_map[button]
            log.debug("emit button release: %s event=%s", button, event)
            await asyncio.to_thread(self._device.emit, event, 0)  # type: ignore

    async def set_axis(self, axis: Axis, value: int) -> None:
        self._ensure_device()
        assert self._device is not None
        if axis not in self._stick_axis_map:
            log.warning("No uinput mapping for axis %s", axis)
            return
        uinput_axis = self._stick_axis_map[axis]
        raw = _scale_axis(value)
        log.debug("emit axis: %s uinput=%s raw=%d", axis, uinput_axis, raw)
        await asyncio.to_thread(self._device.emit, uinput_axis, raw)  # type: ignore

    async def cleanup(self) -> None:
        """Destroy the uinput device."""
        if self._device is not None:
            with contextlib.suppress(Exception):
                self._device.__del__()  # type: ignore
            self._device = None
            log.info("uinput device destroyed")
