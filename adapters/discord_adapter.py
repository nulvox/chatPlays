"""Discord chat adapter for discord-plays.

IMPORTANT — Discord bot setup:
  1. Create a bot at https://discord.com/developers/applications
  2. Under Bot → Privileged Gateway Intents, enable **Message Content Intent**
     (required to read message text; the bot will not function without this)
  3. Invite the bot with scopes: bot, and permissions: Read Messages / View Channels
  4. Copy the token into config.toml [discord].token or the DISCORD_TOKEN env var
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import discord

from adapters import ChatAdapter

if TYPE_CHECKING:
    from config import Config
    from queue_engine import QueueEngine

log = logging.getLogger(__name__)


class DiscordAdapter(ChatAdapter):
    """discord.py-based adapter that relays chat commands to the queue engine."""

    def __init__(
        self,
        config: Config,
        on_command: Callable[[str, str], Awaitable[None]],
        queue_engine: QueueEngine,
    ) -> None:
        super().__init__(on_command)
        self._config = config
        self._queue_engine = queue_engine

        # Per-user rate limiting state
        # last_command_time[user_id] = monotonic timestamp of last accepted command
        self._last_command_time: dict[str, float] = defaultdict(float)
        # window_command_count[user_id] = (window_start_time, count)
        self._window_counts: dict[str, tuple[float, int]] = {}

        intents = discord.Intents.default()
        intents.messages = True         # Receive message events in guilds
        intents.message_content = True  # Privileged intent — must be enabled in dev portal

        self._client = discord.Client(intents=intents)
        self._register_events()

    def _register_events(self) -> None:
        client = self._client
        config = self._config

        @client.event
        async def on_ready() -> None:
            log.info("Discord bot ready: %s (id=%s)", client.user, client.user.id if client.user else "?")
            for guild in client.guilds:
                log.info("In guild: %s (id=%s)", guild.name, guild.id)
                for channel in guild.text_channels:
                    log.info("  channel: #%s (id=%s)", channel.name, channel.id)

        @client.event
        async def on_disconnect() -> None:
            log.warning("Discord disconnected — discord.py will attempt to reconnect automatically")

        @client.event
        async def on_resumed() -> None:
            log.info("Discord connection resumed")

        @client.event
        async def on_message(message: discord.Message) -> None:
            log.info("on_message: channel=%s author=%s content=%r", message.channel.id, message.author, message.content)
            # Ignore messages outside the designated channel
            if message.channel.id != config.discord.channel_id:
                log.info("Ignoring message from channel %s (expected %s)", message.channel.id, config.discord.channel_id)
                return
            # Ignore bot's own messages
            if message.author.bot:
                return

            content = message.content.strip()
            user_id = str(message.author.id)
            prefix = config.discord.command_prefix

            if not content.startswith(prefix):
                return

            body = content[len(prefix):].strip().lower()

            # ── Operator commands ─────────────────────────────────────────────
            if body.startswith("mode "):
                await self._handle_mode(message, body[5:].strip())
                return
            if body == "status":
                await self._handle_status(message)
                return
            if body == "pause":
                await self._handle_pause(message)
                return
            if body == "resume":
                await self._handle_resume(message)
                return

            # ── Rate limiting ─────────────────────────────────────────────────
            if not self._check_rate_limit(user_id):
                log.debug("Rate limited: user=%s", user_id)
                return

            # ── Pass to queue engine ──────────────────────────────────────────
            log.debug("Accepted command from user=%s: %s", user_id, content)
            await self.on_command(user_id, content)

    def _check_rate_limit(self, user_id: str) -> bool:
        """Return True if the command should be accepted, False if rate-limited."""
        now = time.monotonic()
        cfg = self._config.rate_limit

        # Per-user cooldown
        last = self._last_command_time.get(user_id, 0.0)
        if now - last < cfg.cooldown_seconds:
            return False

        # Per-window count limit
        window_start, count = self._window_counts.get(user_id, (now, 0))
        window_duration = self._config.queue.vote_window_seconds
        if now - window_start > window_duration:
            # New window
            window_start = now
            count = 0
        if count >= cfg.max_per_window:
            return False

        self._last_command_time[user_id] = now
        self._window_counts[user_id] = (window_start, count + 1)
        return True

    def _is_operator(self, member: discord.Member | discord.User) -> bool:
        """Return True if the user has Manage Server permission or higher."""
        if isinstance(member, discord.Member):
            return member.guild_permissions.manage_guild
        # DM context — not an operator
        return False

    async def _handle_mode(self, message: discord.Message, mode_str: str) -> None:
        if not self._is_operator(message.author):
            log.info(
                "Non-operator mode change attempt: user=%s", message.author.id
            )
            return
        if mode_str not in ("fifo", "vote"):
            await message.channel.send(f"Unknown mode '{mode_str}'. Use: `!mode fifo` or `!mode vote`")
            return
        self._queue_engine.set_mode(mode_str)  # type: ignore[arg-type]
        log.info("Operator %s switched mode to %s", message.author.id, mode_str)
        await message.channel.send(f"Mode switched to **{mode_str}**")

    async def _handle_status(self, message: discord.Message) -> None:
        status = self._queue_engine.get_status()
        await message.channel.send(
            f"**Status** | mode: {status['mode']} | "
            f"queue depth: {status['queue_depth']} | "
            f"paused: {status['paused']} | "
            f"vote window: {status.get('vote_window_remaining', 'n/a')}"
        )

    async def _handle_pause(self, message: discord.Message) -> None:
        if not self._is_operator(message.author):
            return
        self._queue_engine.pause()
        log.info("Operator %s paused execution", message.author.id)
        await message.channel.send("Execution **paused**")

    async def _handle_resume(self, message: discord.Message) -> None:
        if not self._is_operator(message.author):
            return
        self._queue_engine.resume()
        log.info("Operator %s resumed execution", message.author.id)
        await message.channel.send("Execution **resumed**")

    async def start(self) -> None:
        log.info("Starting Discord adapter (channel_id=%d)", self._config.discord.channel_id)
        await self._client.start(self._config.discord.token)

    async def stop(self) -> None:
        log.info("Stopping Discord adapter")
        await self._client.close()
