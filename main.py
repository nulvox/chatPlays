"""chatPlays — entry point.

Wires together config, controller, queue engine, and Discord adapter,
then runs the asyncio event loop until SIGINT/SIGTERM.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys

from adapters.discord_adapter import DiscordAdapter
from config import ConfigError, load_config
from controller import get_controller
from parser import set_limits
from queue_engine import QueueEngine


def _configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


async def _run(config_path: str) -> None:
    config = load_config(config_path)
    set_limits(
        max_hold_ms=config.controller.max_hold_ms,
        max_steps=config.controller.max_sequence_steps,
        max_total_ms=config.controller.max_total_duration_ms,
    )

    controller = get_controller(config)
    engine = QueueEngine(config, controller)

    adapter = DiscordAdapter(
        config=config,
        on_command=engine.on_command,
        queue_engine=engine,
    )

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logging.getLogger(__name__).info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await engine.start()

    # Run Discord adapter and the stop-event watcher concurrently
    discord_task = asyncio.create_task(adapter.start(), name="discord_adapter")
    stop_task = asyncio.create_task(stop_event.wait(), name="stop_event")

    done, pending = await asyncio.wait(
        {discord_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    # Graceful shutdown
    for task in pending:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    # Check if Discord task raised an exception
    for task in done:
        exc = task.exception() if not task.cancelled() else None
        if exc is not None:
            logging.getLogger(__name__).error("Discord adapter error: %s", exc)

    await adapter.stop()
    await engine.stop()
    logging.getLogger(__name__).info("chatPlays shut down cleanly")


def main() -> None:
    _configure_logging()
    log = logging.getLogger(__name__)

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.toml"

    try:
        asyncio.run(_run(config_path))
    except ConfigError as exc:
        log.error("Configuration error: %s", exc)
        sys.exit(1)
    except RuntimeError as exc:
        log.error("Runtime error: %s", exc)
        sys.exit(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
