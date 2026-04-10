"""Controller abstraction layer for discord-plays.

Provides the VirtualController abstract base class and a factory function
`get_controller` that selects the correct platform implementation.
"""

from __future__ import annotations

import asyncio
import sys
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import Config

from parser import Axis, Button, ButtonInput, ChordStep, Sequence, WaitStep


class VirtualController(ABC):
    """Abstract interface for a virtual gamepad device."""

    # ── Abstract primitives (platform implementations must provide these) ─────

    @abstractmethod
    async def press_down(self, button: Button) -> None:
        """Emit a button-down event (or d-pad axis deflection)."""

    @abstractmethod
    async def release_button(self, button: Button) -> None:
        """Emit a button-up event (or d-pad axis centre)."""

    @abstractmethod
    async def set_axis(self, axis: Axis, value: int) -> None:
        """Set an analog axis to *value* (-100..100 percentage)."""

    @abstractmethod
    async def cleanup(self) -> None:
        """Release all resources (device handles, kernel objects, etc.)."""

    # ── Legacy interface (kept for direct single-button use) ─────────────────

    async def press(self, button: ButtonInput) -> None:
        """Press and hold a button for button.hold_ms milliseconds, then release."""
        await self.press_down(button.button)
        await asyncio.sleep(button.hold_ms / 1000.0)
        await self.release_button(button.button)

    async def release(self, button: ButtonInput) -> None:
        """Release a previously held button (used for explicit release if needed)."""
        await self.release_button(button.button)

    # ── Sequence execution (concrete — calls abstract primitives) ────────────

    async def execute_sequence(self, sequence: Sequence) -> None:
        """Execute a full input sequence of chords and waits."""
        for step in sequence.steps:
            if isinstance(step, WaitStep):
                await asyncio.sleep(step.wait_ms / 1000.0)
            else:
                await self._execute_chord(step)

    async def _execute_chord(self, chord: ChordStep) -> None:
        """Press all buttons / set all axes, hold, then release."""
        # Set axes
        for ai in chord.axes:
            await self.set_axis(ai.axis, ai.value)

        # Press all buttons down
        for btn in chord.buttons:
            await self.press_down(btn.button)

        if chord.buttons:
            # Staggered release: release each button when its hold_ms elapses
            sorted_btns = sorted(chord.buttons, key=lambda b: b.hold_ms)
            elapsed = 0
            for btn in sorted_btns:
                wait = btn.hold_ms - elapsed
                if wait > 0:
                    await asyncio.sleep(wait / 1000.0)
                    elapsed = btn.hold_ms
                await self.release_button(btn.button)

        # Reset axes to centre
        for ai in chord.axes:
            await self.set_axis(ai.axis, 0)


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
