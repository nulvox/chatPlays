# Agent Prompt: Discord Plays — Chat-Driven Steam Controller Emulator

## Project Overview

Build a Python daemon called **`discord-plays`** that:
1. Connects to Discord and listens for controller button commands in a designated channel
2. Queues those commands for execution with two switchable dispatch modes
3. Delivers inputs to a virtual Xbox 360 (XInput) gamepad that Steam recognizes as a real controller

The architecture must treat the Discord integration as a **discrete, swappable chat adapter module** so it can be replaced or extended to support other platforms (Twitch IRC, Matrix, etc.) without touching core logic.

---

## Target Platform

- **Primary:** Linux (via `python-uinput` / `/dev/uinput`)
- **Secondary:** Windows (via `vgamepad` wrapping ViGEm) — implement behind a platform-detection shim; feature parity not required at launch but the abstraction layer must support it
- **Python version:** 3.11+
- **Package manager:** Use `pyproject.toml` + `uv` or `poetry`

---

## Architecture

### Module Boundaries

```
discord-plays/
├── main.py                  # Entry point, wires modules together
├── config.py                # Loads and validates config.toml
├── queue_engine.py          # Command queue, dispatch loop, mode switching
├── controller/
│   ├── __init__.py          # Abstract base: VirtualController
│   ├── linux.py             # uinput implementation
│   └── windows.py           # vgamepad implementation (stub acceptable at launch)
├── adapters/
│   ├── __init__.py          # Abstract base: ChatAdapter
│   └── discord_adapter.py   # discord.py implementation
└── parser.py                # Command parsing and validation
```

### Abstract Interfaces (must be defined, not skipped)

**`ChatAdapter` (adapters/__init__.py)**
```python
class ChatAdapter(ABC):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    # Must call self.on_command(user_id: str, raw: str) when a valid command arrives
    on_command: Callable[[str, str], Awaitable[None]]
```

**`VirtualController` (controller/__init__.py)**
```python
class VirtualController(ABC):
    async def press(self, button: ButtonInput) -> None: ...
    async def release(self, button: ButtonInput) -> None: ...
    async def cleanup(self) -> None: ...
```

---

## Configuration (`config.toml`)

All user-tunable values live here. The daemon must fail fast with a clear error if required fields are missing.

```toml
[discord]
token = ""                  # Bot token (also accepts env var DISCORD_TOKEN)
channel_id = 0              # Snowflake ID of the designated command channel
command_prefix = "!"        # Prefix for commands (e.g., !a, !start)

[queue]
mode = "fifo"               # "fifo" | "vote" — switchable at runtime via bot command
vote_window_seconds = 5     # Duration of each voting window (vote mode only)
fifo_execute_interval = 0.1 # Seconds between command executions (fifo mode only)

[rate_limit]
cooldown_seconds = 1.0      # Per-user cooldown between accepted commands
max_per_window = 3          # Max commands accepted per user per voting window
                            # In fifo mode, max_per_window applies per vote_window_seconds

[controller]
press_duration_ms = 100     # How long a button press is held before release
platform = "auto"           # "auto" | "linux" | "windows"
```

---

## Command Parser (`parser.py`)

### Phase 1 (implement now)
- Parse `!<button>` commands where `<button>` is a case-insensitive name from the supported button map
- Return a structured `ButtonInput(button: Button, hold_ms: int)` datatype
- Reject unknown buttons silently (no response to user) or with a configurable quiet-fail flag

### Phase 2 (stub interface, do not implement logic)
- `!<button> <duration>` — e.g., `!a 500` for 500ms hold
- Parser should have a placeholder branch and a comment indicating where duration parsing goes

### Phase 3 (stub interface, do not implement logic)
- `!<seq>` — sequences like `!up up down down left right`
- Parser should have a placeholder branch and a comment indicating where sequence parsing goes

### Button Map (Xbox 360 layout)
```
a, b, x, y
lb, rb, lt, rt
start, back, guide
up, down, left, right       # D-pad
ls, rs                      # Stick clicks
```

---

## Queue Engine (`queue_engine.py`)

### FIFO Mode
- Commands enter an `asyncio.Queue`
- Dispatch loop pops and executes one command every `fifo_execute_interval` seconds
- Queue depth should be capped (configurable, default 50) — overflow silently drops oldest

### Vote Mode
- Collect all commands received during `vote_window_seconds`
- At window end, tally votes by button; winning button executes once
- Ties broken by whichever button was submitted first in the window
- After execution, immediately start the next window

### Runtime Mode Switching
- Expose `set_mode(mode: Literal["fifo", "vote"])` method
- Switching drains/discards the current queue before activating new mode
- Discord adapter should expose `!mode fifo` and `!mode vote` as operator-only commands (restrict to users with Discord Manage Server permission or a configurable role ID)

---

## Discord Adapter (`adapters/discord_adapter.py`)

- Use `discord.py` (not `nextcord`, not `interactions.py`)
- Bot requires only `MESSAGE_CONTENT` intent (privileged — document this clearly in README)
- Listen only in the configured `channel_id`
- Apply rate limiting before passing to `on_command`; silently drop rate-limited messages
- Operator commands (`!mode`, `!status`, `!pause`, `!resume`) checked before passing to parser
- `!status` replies with current mode, queue depth, vote window state
- `!pause` / `!resume` halts/resumes command execution without disconnecting

---

## Controller Layer

### Linux (`controller/linux.py`)
- Use `python-uinput`
- Create device with `uinput.Device([...])` listing all Xbox button codes
- Map `Button` enum values to `uinput` event constants
- The device must appear to the kernel as a gamepad (set correct `BUS_USB`, vendor/product IDs for Xbox 360 controller: `045e:028e`)
- Steam must detect it via `/dev/uinput` without requiring special Steam Input configuration

### Windows (`controller/windows.py`)
- Use `vgamepad`
- Stub is acceptable: implement `press`/`release` as no-ops with a logged warning, but import guard must not crash on Linux
- Add a TODO comment block describing what the full implementation requires

### Platform Detection (`controller/__init__.py`)
```python
def get_controller(config) -> VirtualController:
    platform = config.controller.platform
    if platform == "auto":
        platform = "linux" if sys.platform.startswith("linux") else "windows"
    if platform == "linux":
        from .linux import LinuxController
        return LinuxController(config)
    ...
```

---

## Error Handling & Resilience

- Discord disconnects: `discord.py` handles reconnect internally; log disconnect/reconnect events
- `uinput` device creation failure: fail fast with actionable error (common cause: user not in `input` group, or `uinput` module not loaded)
- Config parse errors: print field name and expected type, exit code 1
- All async exceptions in the dispatch loop must be caught, logged, and the loop must continue

---

## Logging

- Use Python `logging` module, not print statements
- Log level configurable via `LOG_LEVEL` env var (default: `INFO`)
- Format: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
- Log every accepted command: `user_id`, `button`, `mode`, `queue_depth`
- Log every executed command: `button`, `hold_ms`, `dispatch_mode`
- Log all operator commands and who issued them

---

## README Requirements

The README must include:

1. **Prerequisites** — `uinput` kernel module loading (`modprobe uinput`, persistence via `/etc/modules-load.d/`), user group membership (`sudo usermod -aG input $USER`)
2. **Discord bot setup** — enabling `MESSAGE_CONTENT` privileged intent in the developer portal
3. **Config reference** — every `config.toml` field with type, default, and description
4. **Adapter extension guide** — how to implement a new `ChatAdapter` subclass (Twitch example skeleton)
5. **Steam compatibility note** — that no special Steam Input profile is needed; the device presents as a native Xbox 360 controller

---

## Deliverables Checklist

- [ ] All module files created with correct imports and no circular dependencies
- [ ] `ChatAdapter` and `VirtualController` abstract bases fully defined
- [ ] Phase 2 and 3 parser stubs present with TODO comments
- [ ] Windows controller stub present, import-safe on Linux
- [ ] `config.toml` example with all fields populated with defaults
- [ ] `pyproject.toml` with pinned dependencies
- [ ] README covering all five sections above
- [ ] `main.py` runnable end-to-end on Linux with a valid Discord token and `config.toml`

---

## Out of Scope for This Build

- Analog stick axis input (architecture should not preclude it, but do not implement)
- Web UI or dashboard
- Persistent command history / database
- Twitch adapter implementation (only the abstract interface needs to support it)
