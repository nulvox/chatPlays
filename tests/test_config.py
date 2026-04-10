"""Tests for config.py."""

import textwrap
from pathlib import Path

import pytest

from config import ConfigError, load_config


def write_config(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(textwrap.dedent(content))
    return p


VALID_TOML = """
    [discord]
    token = "test-token"
    channel_id = 123456789
    command_prefix = "!"

    [queue]
    mode = "fifo"
    vote_window_seconds = 5
    fifo_execute_interval = 0.1

    [rate_limit]
    cooldown_seconds = 1.0
    max_per_window = 3

    [controller]
    press_duration_ms = 100
    platform = "auto"
"""


class TestValidConfig:
    def test_loads_successfully(self, tmp_path):
        p = write_config(tmp_path, VALID_TOML)
        cfg = load_config(p)
        assert cfg.discord.token == "test-token"
        assert cfg.discord.channel_id == 123456789
        assert cfg.queue.mode == "fifo"
        assert cfg.queue.vote_window_seconds == 5.0
        assert cfg.rate_limit.cooldown_seconds == 1.0
        assert cfg.controller.press_duration_ms == 100

    def test_default_max_depth(self, tmp_path):
        p = write_config(tmp_path, VALID_TOML)
        cfg = load_config(p)
        assert cfg.queue.max_depth == 50

    def test_vote_mode(self, tmp_path):
        toml = VALID_TOML.replace('mode = "fifo"', 'mode = "vote"')
        p = write_config(tmp_path, toml)
        cfg = load_config(p)
        assert cfg.queue.mode == "vote"

    def test_discord_token_from_env(self, tmp_path, monkeypatch):
        toml = VALID_TOML.replace('token = "test-token"', 'token = ""')
        p = write_config(tmp_path, toml)
        monkeypatch.setenv("DISCORD_TOKEN", "env-token")
        cfg = load_config(p)
        assert cfg.discord.token == "env-token"

    def test_env_token_overrides_config(self, tmp_path, monkeypatch):
        p = write_config(tmp_path, VALID_TOML)
        monkeypatch.setenv("DISCORD_TOKEN", "env-token")
        cfg = load_config(p)
        assert cfg.discord.token == "env-token"


class TestMissingFields:
    def test_missing_token_and_no_env(self, tmp_path, monkeypatch):
        toml = VALID_TOML.replace('token = "test-token"', 'token = ""')
        p = write_config(tmp_path, toml)
        monkeypatch.delenv("DISCORD_TOKEN", raising=False)
        with pytest.raises(ConfigError, match="token"):
            load_config(p)

    def test_missing_channel_id(self, tmp_path):
        toml = "\n".join(line for line in VALID_TOML.splitlines() if "channel_id" not in line)
        p = write_config(tmp_path, toml)
        with pytest.raises(ConfigError, match="channel_id"):
            load_config(p)

    def test_missing_mode(self, tmp_path):
        toml = "\n".join(line for line in VALID_TOML.splitlines() if "mode" not in line)
        p = write_config(tmp_path, toml)
        with pytest.raises(ConfigError, match="mode"):
            load_config(p)


class TestInvalidValues:
    def test_invalid_mode(self, tmp_path):
        toml = VALID_TOML.replace('mode = "fifo"', 'mode = "random"')
        p = write_config(tmp_path, toml)
        with pytest.raises(ConfigError, match="mode"):
            load_config(p)

    def test_invalid_platform(self, tmp_path):
        toml = VALID_TOML.replace('platform = "auto"', 'platform = "macos"')
        p = write_config(tmp_path, toml)
        with pytest.raises(ConfigError, match="platform"):
            load_config(p)


class TestFileErrors:
    def test_missing_file(self, tmp_path):
        with pytest.raises(ConfigError, match="not found"):
            load_config(tmp_path / "nonexistent.toml")

    def test_invalid_toml(self, tmp_path):
        p = tmp_path / "config.toml"
        p.write_text("this is [not valid toml ][[[")
        with pytest.raises(ConfigError):
            load_config(p)
