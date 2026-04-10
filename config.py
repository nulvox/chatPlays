"""Configuration loading and validation for chatPlays."""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class DiscordConfig:
    token: str
    channel_id: int
    command_prefix: str


@dataclass(frozen=True)
class QueueConfig:
    mode: Literal["fifo", "vote"]
    vote_window_seconds: float
    fifo_execute_interval: float
    max_depth: int


@dataclass(frozen=True)
class RateLimitConfig:
    cooldown_seconds: float
    max_per_window: int
    global_max_per_minute: int


@dataclass(frozen=True)
class ControllerConfig:
    press_duration_ms: int
    platform: Literal["auto", "linux", "windows"]
    max_hold_ms: int = 5000
    max_sequence_steps: int = 20
    max_total_duration_ms: int = 10000


@dataclass(frozen=True)
class Config:
    discord: DiscordConfig
    queue: QueueConfig
    rate_limit: RateLimitConfig
    controller: ControllerConfig


def _require(
    section: dict[str, object], key: str, expected_type: type, section_name: str
) -> object:
    """Extract a required field, raising ConfigError if missing or wrong type."""
    if key not in section:
        raise ConfigError(f"[{section_name}] missing required field: '{key}'")
    val = section[key]
    if not isinstance(val, expected_type):
        raise ConfigError(
            f"[{section_name}] '{key}' must be {expected_type.__name__}, got {type(val).__name__}"
        )
    return val


class ConfigError(Exception):
    """Raised when configuration is invalid or missing required fields."""


def load_config(path: str | Path = "config.toml") -> Config:
    """Load and validate configuration from a TOML file.

    The DISCORD_TOKEN and DISCORD_CHANNEL_ID env vars override their
    [discord] counterparts if set.
    Raises ConfigError with a descriptive message on any validation failure.
    """
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")

    try:
        raw = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Failed to parse {path}: {exc}") from exc

    # ── [discord] ──────────────────────────────────────────────────────────────
    disc_raw = raw.get("discord", {})
    token: str = os.environ.get("DISCORD_TOKEN", "") or str(
        _require(disc_raw, "token", str, "discord")
    )
    if not token:
        raise ConfigError(
            "[discord] 'token' is empty. Set it in config.toml or via DISCORD_TOKEN env var."
        )
    channel_id_env = os.environ.get("DISCORD_CHANNEL_ID", "")
    if channel_id_env:
        try:
            channel_id = int(channel_id_env)
        except ValueError as exc:
            raise ConfigError("DISCORD_CHANNEL_ID env var must be a valid integer.") from exc
    else:
        channel_id = int(_require(disc_raw, "channel_id", int, "discord"))  # type: ignore
    command_prefix = str(_require(disc_raw, "command_prefix", str, "discord"))

    discord_cfg = DiscordConfig(
        token=token,
        channel_id=channel_id,
        command_prefix=command_prefix,
    )

    # ── [queue] ────────────────────────────────────────────────────────────────
    q_raw = raw.get("queue", {})
    mode_raw = str(_require(q_raw, "mode", str, "queue"))
    if mode_raw not in ("fifo", "vote"):
        raise ConfigError(f"[queue] 'mode' must be 'fifo' or 'vote', got '{mode_raw}'")
    mode: Literal["fifo", "vote"] = mode_raw  # type: ignore

    vote_window = float(_require(q_raw, "vote_window_seconds", (int, float), "queue"))  # type: ignore
    fifo_interval = float(_require(q_raw, "fifo_execute_interval", (int, float), "queue"))  # type: ignore
    max_depth = int(q_raw.get("max_depth", 50))

    queue_cfg = QueueConfig(
        mode=mode,
        vote_window_seconds=vote_window,
        fifo_execute_interval=fifo_interval,
        max_depth=max_depth,
    )

    # ── [rate_limit] ───────────────────────────────────────────────────────────
    rl_raw = raw.get("rate_limit", {})
    cooldown = float(_require(rl_raw, "cooldown_seconds", (int, float), "rate_limit"))  # type: ignore
    max_per_window = int(_require(rl_raw, "max_per_window", int, "rate_limit"))  # type: ignore

    global_max_per_minute = int(rl_raw.get("global_max_per_minute", 60))

    rate_limit_cfg = RateLimitConfig(
        cooldown_seconds=cooldown,
        max_per_window=max_per_window,
        global_max_per_minute=global_max_per_minute,
    )

    # ── [controller] ───────────────────────────────────────────────────────────
    ctrl_raw = raw.get("controller", {})
    press_duration_ms = int(_require(ctrl_raw, "press_duration_ms", int, "controller"))  # type: ignore
    platform_raw = str(_require(ctrl_raw, "platform", str, "controller"))
    if platform_raw not in ("auto", "linux", "windows"):
        raise ConfigError(
            f"[controller] 'platform' must be 'auto', 'linux', or 'windows', got '{platform_raw}'"
        )
    platform: Literal["auto", "linux", "windows"] = platform_raw  # type: ignore

    max_hold_ms = int(ctrl_raw.get("max_hold_ms", 5000))
    max_sequence_steps = int(ctrl_raw.get("max_sequence_steps", 20))
    max_total_duration_ms = int(ctrl_raw.get("max_total_duration_ms", 10000))

    controller_cfg = ControllerConfig(
        press_duration_ms=press_duration_ms,
        platform=platform,
        max_hold_ms=max_hold_ms,
        max_sequence_steps=max_sequence_steps,
        max_total_duration_ms=max_total_duration_ms,
    )

    return Config(
        discord=discord_cfg,
        queue=queue_cfg,
        rate_limit=rate_limit_cfg,
        controller=controller_cfg,
    )


if __name__ == "__main__":
    try:
        cfg = load_config()
        print(f"Config loaded successfully: mode={cfg.queue.mode}")
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        sys.exit(1)
