"""Command parser for discord-plays.

Phase 1: Single button press — !<button>
Phase 2: Button + duration  — !<button> <ms>   (stub)
Phase 3: Button sequence    — !<b1> <b2> ...    (stub)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

log = logging.getLogger(__name__)


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


_BUTTON_LOOKUP: dict[str, Button] = {b.value: b for b in Button}


@dataclass(frozen=True)
class ButtonInput:
    button: Button
    hold_ms: int


def parse_command(raw: str, prefix: str, default_hold_ms: int) -> ButtonInput | None:
    """Parse a raw chat message into a ButtonInput.

    Returns None if the message is not a valid command (silently rejected).

    Args:
        raw:             The full message text, e.g. "!a" or "!lb 500".
        prefix:          Command prefix from config, e.g. "!".
        default_hold_ms: Default hold duration when the user supplies none.
    """
    if not raw.startswith(prefix):
        return None

    body = raw[len(prefix) :].strip()
    if not body:
        return None

    parts = body.lower().split()

    # ── Phase 1: single button ─────────────────────────────────────────────────
    if len(parts) == 1:
        btn = _BUTTON_LOOKUP.get(parts[0])
        if btn is None:
            log.debug("Unknown button '%s' — dropping", parts[0])
            return None
        return ButtonInput(button=btn, hold_ms=default_hold_ms)

    # ── Phase 2: button + duration — !<button> <ms> ────────────────────────────
    # TODO(phase2): Parse optional hold duration from parts[1] (integer ms).
    #   Validate: must be a positive integer, cap at a configured maximum.
    #   Example: "!a 500" → ButtonInput(Button.A, 500)
    if len(parts) == 2 and parts[0] in _BUTTON_LOOKUP:
        log.debug("Phase 2 (duration) not yet implemented — treating as single press")
        btn = _BUTTON_LOOKUP[parts[0]]
        return ButtonInput(button=btn, hold_ms=default_hold_ms)

    # ── Phase 3: button sequence — !<b1> <b2> … ───────────────────────────────
    # TODO(phase3): Parse multi-button sequences.
    #   Validate each token against _BUTTON_LOOKUP; reject the whole command if
    #   any token is unknown. Return a list[ButtonInput] or a new SequenceInput
    #   datatype; the queue engine will need to handle it.
    #   Example: "!up up down down left right" → [ButtonInput(...), ...]
    log.debug("Phase 3 (sequence) not yet implemented — dropping multi-part command")
    return None
