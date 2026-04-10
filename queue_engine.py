"""Command queue and dispatch engine for discord-plays.

Supports two modes:
  fifo — Execute commands in order, one every fifo_execute_interval seconds.
  vote — Collect commands for vote_window_seconds, then execute the winner once.

Runtime mode switching drains/discards the current queue before activating
the new mode. Pause/resume halts execution without disconnecting.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import Counter
from typing import TYPE_CHECKING, Literal

from parser import Sequence, parse_command

if TYPE_CHECKING:
    from config import Config
    from controller import VirtualController

log = logging.getLogger(__name__)


class QueueEngine:
    """Core dispatch loop. Thread-safe between asyncio tasks."""

    def __init__(self, config: Config, controller: VirtualController) -> None:
        self._config = config
        self._controller = controller
        self._mode: Literal["fifo", "vote"] = config.queue.mode
        self._paused = False
        self._running = False

        # FIFO state
        self._fifo_queue: asyncio.Queue[Sequence] = asyncio.Queue(maxsize=config.queue.max_depth)

        # Vote state
        # Each entry: (monotonic_time, Sequence) — time for tie-breaking
        self._vote_buffer: list[tuple[float, Sequence]] = []
        self._vote_window_start: float = 0.0

        self._dispatch_task: asyncio.Task[None] | None = None

        # Timesharing limits (0 = unlimited, adjustable at runtime)
        self._max_keypresses: int = 0
        self._max_command_duration_ms: int = 0

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_max_keypresses(self, value: int) -> None:
        """Set the per-command keypress limit (0 = unlimited)."""
        self._max_keypresses = max(0, value)
        log.info("Max keypresses per command set to %d (0=unlimited)", self._max_keypresses)

    def set_max_command_duration_ms(self, value: int) -> None:
        """Set the per-command duration limit in ms (0 = unlimited)."""
        self._max_command_duration_ms = max(0, value)
        log.info("Max command duration set to %dms (0=unlimited)", self._max_command_duration_ms)

    async def on_command(self, user_id: str, raw: str) -> None:
        """Called by the chat adapter when a validated, rate-limited command arrives."""
        seq = parse_command(
            raw,
            self._config.discord.command_prefix,
            self._config.controller.press_duration_ms,
            max_keypresses=self._max_keypresses,
            max_command_duration_ms=self._max_command_duration_ms,
        )
        if seq is None:
            return

        if self._mode == "fifo":
            await self._enqueue_fifo(user_id, seq)
        else:
            self._enqueue_vote(user_id, seq)

    def set_mode(self, mode: Literal["fifo", "vote"]) -> None:
        """Switch dispatch mode, draining/discarding the current queue first."""
        if mode == self._mode:
            return
        log.info("Switching mode %s → %s; draining queue", self._mode, mode)
        self._drain()
        self._mode = mode

    def pause(self) -> None:
        self._paused = True
        log.info("Queue engine paused")

    def resume(self) -> None:
        self._paused = False
        log.info("Queue engine resumed")

    def get_status(self) -> dict[str, object]:
        status: dict[str, object] = {
            "mode": self._mode,
            "paused": self._paused,
            "queue_depth": self._fifo_queue.qsize()
            if self._mode == "fifo"
            else len(self._vote_buffer),
        }
        if self._mode == "vote":
            elapsed = time.monotonic() - self._vote_window_start
            remaining = max(0.0, self._config.queue.vote_window_seconds - elapsed)
            status["vote_window_remaining"] = f"{remaining:.1f}s"
        status["max_keypresses"] = self._max_keypresses or "off"
        status["max_command_duration_ms"] = self._max_command_duration_ms or "off"
        return status

    async def start(self) -> None:
        """Start the background dispatch loop."""
        self._running = True
        self._vote_window_start = time.monotonic()
        self._dispatch_task = asyncio.create_task(self._dispatch_loop(), name="dispatch_loop")
        log.info("Queue engine started in %s mode", self._mode)

    async def stop(self) -> None:
        """Stop the dispatch loop and clean up the controller."""
        self._running = False
        if self._dispatch_task is not None:
            self._dispatch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._dispatch_task
        await self._controller.cleanup()
        log.info("Queue engine stopped")

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _enqueue_fifo(self, user_id: str, seq: Sequence) -> None:
        if self._fifo_queue.full():
            # Drop the oldest command to make room (overflow policy: drop oldest)
            try:
                dropped = self._fifo_queue.get_nowait()
                log.debug("Queue full — dropped oldest: %s", dropped.canonical)
            except asyncio.QueueEmpty:
                pass
        await self._fifo_queue.put(seq)
        log.info(
            "Accepted command: user=%s cmd=%s mode=fifo queue_depth=%d",
            user_id,
            seq.canonical,
            self._fifo_queue.qsize(),
        )

    def _enqueue_vote(self, user_id: str, seq: Sequence) -> None:
        self._vote_buffer.append((time.monotonic(), seq))
        log.info(
            "Accepted command: user=%s cmd=%s mode=vote queue_depth=%d",
            user_id,
            seq.canonical,
            len(self._vote_buffer),
        )

    def _drain(self) -> None:
        """Discard all pending commands in both queues."""
        while not self._fifo_queue.empty():
            try:
                self._fifo_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._vote_buffer.clear()

    # ── Dispatch loop ──────────────────────────────────────────────────────────

    async def _dispatch_loop(self) -> None:
        """Main loop — runs until self._running is False."""
        while self._running:
            try:
                if self._mode == "fifo":
                    await self._fifo_tick()
                else:
                    await self._vote_tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Unhandled error in dispatch loop — continuing")

    async def _fifo_tick(self) -> None:
        interval = self._config.queue.fifo_execute_interval
        if self._paused:
            await asyncio.sleep(interval)
            return

        try:
            seq = await asyncio.wait_for(self._fifo_queue.get(), timeout=interval)
        except TimeoutError:
            return  # nothing in queue, loop again

        await self._execute(seq, "fifo")
        # Respect the configured interval between presses
        await asyncio.sleep(interval)

    async def _vote_tick(self) -> None:
        window = self._config.queue.vote_window_seconds
        now = time.monotonic()
        elapsed = now - self._vote_window_start
        remaining = window - elapsed

        if remaining > 0:
            await asyncio.sleep(min(remaining, 0.1))  # wake up at most every 100ms
            return

        # Window expired — tally votes
        buffer = list(self._vote_buffer)
        self._vote_buffer.clear()
        self._vote_window_start = time.monotonic()

        if not buffer or self._paused:
            return

        winner = self._tally_votes(buffer)
        if winner is not None:
            await self._execute(winner, "vote")

    @staticmethod
    def _tally_votes(buffer: list[tuple[float, Sequence]]) -> Sequence | None:
        """Return the winning Sequence by vote count; break ties by earliest submission."""
        if not buffer:
            return None

        counts: Counter[str] = Counter(entry.canonical for _, entry in buffer)
        max_votes = max(counts.values())
        winners = [name for name, cnt in counts.items() if cnt == max_votes]

        if len(winners) == 1:
            winning_name = winners[0]
        else:
            # Tie-break: earliest submission time
            for _, entry in buffer:
                if entry.canonical in winners:
                    winning_name = entry.canonical
                    break
            else:
                winning_name = winners[0]

        # Return the first Sequence with the winning canonical name
        for _, entry in buffer:
            if entry.canonical == winning_name:
                return entry
        return None

    async def _execute(self, seq: Sequence, dispatch_mode: str) -> None:
        log.info(
            "Executing: cmd=%s dispatch_mode=%s",
            seq.canonical,
            dispatch_mode,
        )
        try:
            await self._controller.execute_sequence(seq)
        except Exception:
            log.exception("Controller error while executing %s", seq.canonical)
