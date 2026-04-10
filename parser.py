"""Command parser for chatPlays.

Syntax
------
command   = PREFIX sequence
sequence  = step (" " step)*
step      = chord | wait
chord     = input ("+" input)*
input     = button_press | axis_set
button_press = BUTTON [":" HOLD_MS]
axis_set     = AXIS ":" VALUE
wait         = "~" MS

Examples:
  !a              single button press
  !a+b            chord (simultaneous)
  !a:500          custom hold duration
  !down right a   three-step sequence
  !a ~200 b       press, wait, press
  !lx:70+ly:-70   analog stick position
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

log = logging.getLogger(__name__)


# ── Enums ─────────────────────────────────────────────────────────────────────


class Button(StrEnum):
    """Xbox 360 button names understood by the parser."""

    A = "a"
    B = "b"
    X = "x"
    Y = "y"
    LB = "lb"
    RB = "rb"
    LT = "lt"
    RT = "rt"
    START = "start"
    BACK = "back"
    GUIDE = "guide"
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    LS = "ls"
    RS = "rs"


class Axis(StrEnum):
    """Analog stick axes."""

    LX = "lx"
    LY = "ly"
    RX = "rx"
    RY = "ry"


_BUTTON_LOOKUP: dict[str, Button] = {b.value: b for b in Button}
_AXIS_LOOKUP: dict[str, Axis] = {a.value: a for a in Axis}


# ── Data types ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ButtonInput:
    button: Button
    hold_ms: int


@dataclass(frozen=True)
class AxisInput:
    axis: Axis
    value: int  # -100..100 (percentage of full deflection)


@dataclass(frozen=True)
class WaitStep:
    wait_ms: int


@dataclass(frozen=True)
class ChordStep:
    buttons: tuple[ButtonInput, ...]
    axes: tuple[AxisInput, ...]


Step = ChordStep | WaitStep


@dataclass(frozen=True)
class Sequence:
    steps: tuple[Step, ...]
    canonical: str  # normalized string for vote grouping


# ── Validation limits ─────────────────────────────────────────────────────────

_MAX_HOLD_MS = 5000
_MAX_STEPS = 20
_MAX_TOTAL_MS = 10000
_MIN_AXIS = -100
_MAX_AXIS = 100


def set_limits(
    *,
    max_hold_ms: int = _MAX_HOLD_MS,
    max_steps: int = _MAX_STEPS,
    max_total_ms: int = _MAX_TOTAL_MS,
) -> None:
    """Override default validation limits (called from config loading)."""
    global _MAX_HOLD_MS, _MAX_STEPS, _MAX_TOTAL_MS  # noqa: PLW0603
    _MAX_HOLD_MS = max_hold_ms
    _MAX_STEPS = max_steps
    _MAX_TOTAL_MS = max_total_ms


# ── Canonical form ────────────────────────────────────────────────────────────


def _canonical(steps: tuple[Step, ...]) -> str:
    """Build a normalized string representation for vote grouping."""
    parts: list[str] = []
    for step in steps:
        if isinstance(step, WaitStep):
            parts.append(f"~{step.wait_ms}")
        else:
            elements: list[str] = []
            for b in sorted(step.buttons, key=lambda bi: bi.button.value):
                elements.append(
                    f"{b.button.value}:{b.hold_ms}" if b.hold_ms != 0 else b.button.value
                )
            for a in sorted(step.axes, key=lambda ai: ai.axis.value):
                elements.append(f"{a.axis.value}:{a.value}")
            parts.append("+".join(elements))
    return " ".join(parts)


# ── Numpad notation ───────────────────────────────────────────────────────────
# Standard fighting game numpad layout (imagine a number pad):
#   7=UL  8=U  9=UR
#   4=L   5=N  6=R
#   1=DL  2=D  3=DR

_NUMPAD_DIRECTIONS: dict[str, tuple[str, ...]] = {
    "1": ("down", "left"),
    "2": ("down",),
    "3": ("down", "right"),
    "4": ("left",),
    "5": (),  # neutral — no direction
    "6": ("right",),
    "7": ("up", "left"),
    "8": ("up",),
    "9": ("up", "right"),
}


def _expand_numpad(sub_tokens: list[str]) -> list[str]:
    """Expand numpad digits into d-pad button names within a chord's sub-tokens."""
    expanded: list[str] = []
    for st in sub_tokens:
        # Check for numpad with optional :hold suffix
        base = st.split(":")[0] if ":" in st else st
        if base in _NUMPAD_DIRECTIONS:
            suffix = st[len(base) :] if ":" in st else ""  # e.g. ":500"
            dirs = _NUMPAD_DIRECTIONS[base]
            expanded.extend(d + suffix for d in dirs)
        else:
            expanded.append(st)
    return expanded


# ── Parsing ───────────────────────────────────────────────────────────────────


def _parse_sub_token(token: str, default_hold_ms: int) -> ButtonInput | AxisInput | None:
    """Parse a single element within a chord (e.g. 'a', 'a:500', 'lx:70')."""
    if ":" in token:
        name, val_str = token.split(":", 1)
        try:
            val = int(val_str)
        except ValueError:
            log.debug("Non-integer value '%s' — dropping", val_str)
            return None

        if name in _AXIS_LOOKUP:
            if not (_MIN_AXIS <= val <= _MAX_AXIS):
                log.debug("Axis value %d out of range — dropping", val)
                return None
            return AxisInput(axis=_AXIS_LOOKUP[name], value=val)

        if name in _BUTTON_LOOKUP:
            if val <= 0:
                log.debug("Hold duration must be positive — dropping")
                return None
            if val > _MAX_HOLD_MS:
                log.debug("Hold duration %d exceeds max %d — dropping", val, _MAX_HOLD_MS)
                return None
            return ButtonInput(button=_BUTTON_LOOKUP[name], hold_ms=val)

        log.debug("Unknown name '%s' — dropping", name)
        return None

    # No colon — must be a plain button name
    btn = _BUTTON_LOOKUP.get(token)
    if btn is None:
        log.debug("Unknown button '%s' — dropping", token)
        return None
    return ButtonInput(button=btn, hold_ms=default_hold_ms)


def _parse_step(token: str, default_hold_ms: int) -> Step | None:
    """Parse a single space-separated token into a Step."""
    # Wait step: ~200
    if token.startswith("~"):
        try:
            ms = int(token[1:])
        except ValueError:
            log.debug("Non-integer wait '%s' — dropping", token)
            return None
        if ms <= 0:
            log.debug("Wait duration must be positive — dropping")
            return None
        return WaitStep(wait_ms=ms)

    # Chord: a+b or a:500+lx:70 or 3+a (numpad)
    sub_tokens = _expand_numpad(token.split("+"))
    buttons: list[ButtonInput] = []
    axes: list[AxisInput] = []

    for st in sub_tokens:
        if not st:
            log.debug("Empty sub-token in chord — dropping")
            return None
        result = _parse_sub_token(st, default_hold_ms)
        if result is None:
            return None
        if isinstance(result, ButtonInput):
            buttons.append(result)
        else:
            axes.append(result)

    # 5 (neutral) expands to no buttons — valid as a no-op step in sequences
    if not buttons and not axes:
        return None

    return ChordStep(buttons=tuple(buttons), axes=tuple(axes))


def _estimate_duration(steps: tuple[Step, ...]) -> int:
    """Estimate total execution time in ms."""
    total = 0
    for step in steps:
        if isinstance(step, WaitStep):
            total += step.wait_ms
        else:
            if step.buttons:
                total += max(b.hold_ms for b in step.buttons)
    return total


def _count_keypresses(step: Step) -> int:
    """Count button presses in a step (waits and axes don't count)."""
    if isinstance(step, WaitStep):
        return 0
    return len(step.buttons)


def _step_duration(step: Step) -> int:
    """Estimate execution time of a single step in ms."""
    if isinstance(step, WaitStep):
        return step.wait_ms
    if step.buttons:
        return max(b.hold_ms for b in step.buttons)
    return 0


def parse_command(
    raw: str,
    prefix: str,
    default_hold_ms: int,
    *,
    max_keypresses: int = 0,
    max_command_duration_ms: int = 0,
) -> Sequence | None:
    """Parse a raw chat message into a Sequence.

    Returns None if the message is not a valid command (silently rejected).
    If *max_keypresses* or *max_command_duration_ms* are non-zero, the sequence
    is truncated (not rejected) at the first step that would exceed the limit.

    Args:
        raw:                     The full message text.
        prefix:                  Command prefix from config, e.g. "!".
        default_hold_ms:         Default hold duration when the user supplies none.
        max_keypresses:          Truncate after this many button presses (0 = unlimited).
        max_command_duration_ms: Truncate once estimated duration exceeds this (0 = unlimited).
    """
    if not raw.startswith(prefix):
        return None

    body = raw[len(prefix) :].strip()
    if not body:
        return None

    tokens = body.lower().split()

    if len(tokens) > _MAX_STEPS:
        log.debug("Too many steps (%d > %d) — dropping", len(tokens), _MAX_STEPS)
        return None

    steps: list[Step] = []
    total_keys = 0
    total_duration = 0

    for token in tokens:
        step = _parse_step(token, default_hold_ms)
        if step is None:
            return None

        step_keys = _count_keypresses(step)
        step_dur = _step_duration(step)

        # Truncate at the first step that would breach a timesharing limit
        if max_keypresses > 0 and total_keys + step_keys > max_keypresses:
            log.debug(
                "Keypress limit reached (%d) — truncating at step %d",
                max_keypresses,
                len(steps),
            )
            break
        if max_command_duration_ms > 0 and total_duration + step_dur > max_command_duration_ms:
            log.debug(
                "Duration limit reached (%dms) — truncating at step %d",
                max_command_duration_ms,
                len(steps),
            )
            break

        total_keys += step_keys
        total_duration += step_dur
        steps.append(step)

    if not steps:
        return None

    step_tuple = tuple(steps)

    duration = _estimate_duration(step_tuple)
    if duration > _MAX_TOTAL_MS:
        log.debug(
            "Sequence duration %dms exceeds max %dms — dropping",
            duration,
            _MAX_TOTAL_MS,
        )
        return None

    return Sequence(steps=step_tuple, canonical=_canonical(step_tuple))
