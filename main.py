"""discord-plays — entry point.

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
from queue_engine import QueueEngine


def _configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


async def _run() -> None:
    config = load_config()

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
    logging.getLogger(__name__).info("discord-plays shut down cleanly")


def main() -> None:
    _configure_logging()
    log = logging.getLogger(__name__)

    try:
        asyncio.run(_run())
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
