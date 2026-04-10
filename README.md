# discord-plays

A Python daemon that lets Discord chat control a virtual Xbox 360 gamepad — "Twitch Plays" style — on Linux (Steam-compatible) and Windows.

---

## Prerequisites

### Linux

**1. Load the uinput kernel module**

```bash
sudo modprobe uinput
```

To load it automatically on boot, create a persistence file:

```bash
echo "uinput" | sudo tee /etc/modules-load.d/uinput.conf
```

**2. Add your user to the `input` group**

```bash
sudo usermod -aG input $USER
```

Log out and back in (or run `newgrp input` in the current shell) for the group change to take effect.

**3. Install Python dependencies**

```bash
pip install "discord-plays[dev]"
# or with uv:
uv sync
```

### Windows

Install the [ViGEm Bus Driver](https://github.com/ViGEm/ViGEmBus/releases) first, then:

```bash
pip install "discord-plays[windows]"
```

> **Note:** The Windows controller implementation is currently a stub (logs button presses but delivers no input). See `controller/windows.py` for the full implementation guide.

---

## Discord Bot Setup

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and create a new application.
2. Navigate to **Bot** and click **Add Bot**.
3. Under **Privileged Gateway Intents**, enable **Message Content Intent**.
   > This is required. Without it the bot cannot read message text and will not function.
4. Copy the bot token — either paste it into `config.toml` under `[discord].token` or export it as an environment variable:
   ```bash
   export DISCORD_TOKEN="your-token-here"
   ```
5. Invite the bot to your server using the OAuth2 URL generator with scopes `bot` and permissions **Read Messages / View Channels**.
6. Right-click the target channel in Discord (with Developer Mode enabled) and **Copy ID**. Paste this into `config.toml` as `channel_id`.

---

## Config Reference

All configuration lives in `config.toml`. Every field is listed below.

### `[discord]`

| Field | Type | Default | Description |
|---|---|---|---|
| `token` | string | `""` | Bot token. Prefer `DISCORD_TOKEN` env var over storing here. |
| `channel_id` | integer | `0` | Snowflake ID of the channel to listen in. |
| `command_prefix` | string | `"!"` | Prefix before button names, e.g. `!` → `!a`, `!start`. |

### `[queue]`

| Field | Type | Default | Description |
|---|---|---|---|
| `mode` | `"fifo"` \| `"vote"` | `"fifo"` | Dispatch mode. Switchable at runtime via `!mode`. |
| `vote_window_seconds` | float | `5` | Duration of each voting window (vote mode). |
| `fifo_execute_interval` | float | `0.1` | Seconds between command executions (fifo mode). |
| `max_depth` | integer | `50` | FIFO queue capacity; overflow drops the oldest entry. |

### `[rate_limit]`

| Field | Type | Default | Description |
|---|---|---|---|
| `cooldown_seconds` | float | `1.0` | Per-user minimum seconds between accepted commands. |
| `max_per_window` | integer | `3` | Max commands accepted per user per `vote_window_seconds` period. |

### `[controller]`

| Field | Type | Default | Description |
|---|---|---|---|
| `press_duration_ms` | integer | `100` | How long (ms) each button is held before release. |
| `platform` | `"auto"` \| `"linux"` \| `"windows"` | `"auto"` | Force a specific backend; `"auto"` detects the OS. |

---

## Running

```bash
python main.py
# or, after installing as a package:
discord-plays
```

Set `LOG_LEVEL=DEBUG` for verbose output:

```bash
LOG_LEVEL=DEBUG python main.py
```

### Operator Commands

These commands require **Manage Server** Discord permission:

| Command | Description |
|---|---|
| `!mode fifo` | Switch to FIFO dispatch mode |
| `!mode vote` | Switch to vote dispatch mode |
| `!status` | Show current mode, queue depth, and pause state |
| `!pause` | Halt command execution (stays connected) |
| `!resume` | Resume command execution |

---

## Button Reference

| Command | Button |
|---|---|
| `!a` | A |
| `!b` | B |
| `!x` | X |
| `!y` | Y |
| `!lb` | Left Bumper |
| `!rb` | Right Bumper |
| `!lt` | Left Trigger |
| `!rt` | Right Trigger |
| `!start` | Start |
| `!back` | Back / Select |
| `!guide` | Guide (Xbox button) |
| `!up` | D-pad Up |
| `!down` | D-pad Down |
| `!left` | D-pad Left |
| `!right` | D-pad Right |
| `!ls` | Left Stick Click |
| `!rs` | Right Stick Click |

---

## Adapter Extension Guide

To support a new chat platform (e.g. Twitch IRC), subclass `ChatAdapter` from `adapters/__init__.py`:

```python
# adapters/twitch_adapter.py
from adapters import ChatAdapter

class TwitchAdapter(ChatAdapter):
    def __init__(self, config, on_command):
        super().__init__(on_command)
        # Set up your IRC/API client here using config values

    async def start(self) -> None:
        # Connect to Twitch IRC and register a message handler.
        # When a message arrives, call:
        #   await self.on_command(user_id, raw_message_text)
        ...

    async def stop(self) -> None:
        # Disconnect cleanly
        ...
```

Then wire it into `main.py` in place of (or alongside) `DiscordAdapter`. The `on_command` callback and the queue engine are platform-agnostic.

---

## Steam Compatibility

No special Steam Input profile or controller mapping is needed.

On Linux, the virtual device is created with the official Xbox 360 USB vendor/product IDs (`045e:028e`) via `/dev/uinput`. Steam's kernel-level input stack detects it as a native Xbox 360 controller the same way it would detect a physical one plugged in over USB.

If Steam does not detect the controller immediately, try toggling **Steam → Settings → Controller → General Controller Settings** to refresh the device list.

---

## Architecture

```
discord-plays/
├── main.py                  # Entry point — wires modules together
├── config.py                # Loads and validates config.toml
├── queue_engine.py          # Command queue, dispatch loop, mode switching
├── parser.py                # Command parsing and validation
├── controller/
│   ├── __init__.py          # Abstract base (VirtualController) + platform factory
│   ├── linux.py             # python-uinput implementation
│   └── windows.py           # vgamepad stub
└── adapters/
    ├── __init__.py          # Abstract base (ChatAdapter)
    └── discord_adapter.py   # discord.py implementation
```
