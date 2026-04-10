"""Controller abstraction layer for discord-plays.

Provides the VirtualController abstract base class and a factory function
`get_controller` that selects the correct platform implementation.
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import Config

from parser import ButtonInput


class VirtualController(ABC):
    """Abstract interface for a virtual gamepad device."""

    @abstractmethod
    async def press(self, button: ButtonInput) -> None:
        """Press and hold a button for button.hold_ms milliseconds, then release."""

    @abstractmethod
    async def release(self, button: ButtonInput) -> None:
        """Release a previously held button (used for explicit release if needed)."""

    @abstractmethod
    async def cleanup(self) -> None:
        """Release all resources (device handles, kernel objects, etc.)."""


def get_controller(config: Config) -> VirtualController:
    """Factory: return the appropriate VirtualController for the current platform."""
    platform = config.controller.platform
    if platform == "auto":
        platform = "linux" if sys.platform.startswith("linux") else "windows"

    if platform == "linux":
        from controller.linux import LinuxController

        return LinuxController(config)

    if platform == "windows":
        from controller.windows import WindowsController

        return WindowsController(config)

    raise ValueError(f"Unknown platform: {platform!r}")
