"""Chat adapter abstraction for chatPlays.

New adapters (Twitch IRC, Matrix, etc.) must subclass ChatAdapter and implement
start() / stop(). When a valid command arrives the adapter must call
self.on_command(user_id, raw_message).

Example — Twitch IRC skeleton:

    class TwitchAdapter(ChatAdapter):
        def __init__(self, config, on_command):
            super().__init__(on_command)
            self._irc = TwitchIRCClient(
                token=config.twitch.token,
                channel=config.twitch.channel,
            )

        async def start(self) -> None:
            self._irc.on_message = self._handle_message
            await self._irc.connect()

        async def stop(self) -> None:
            await self._irc.disconnect()

        async def _handle_message(self, user_id: str, text: str) -> None:
            await self.on_command(user_id, text)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable


class ChatAdapter(ABC):
    """Abstract base class for all chat platform adapters."""

    def __init__(self, on_command: Callable[[str, str], Awaitable[None]]) -> None:
        self.on_command = on_command

    @abstractmethod
    async def start(self) -> None:
        """Connect to the chat platform and begin listening for messages."""

    @abstractmethod
    async def stop(self) -> None:
        """Disconnect cleanly from the chat platform."""
