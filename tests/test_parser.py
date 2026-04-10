"""Tests for parser.py."""

from parser import (
    Axis,
    AxisInput,
    Button,
    ButtonInput,
    ChordStep,
    Sequence,
    WaitStep,
    parse_command,
    set_limits,
)

PREFIX = "!"
DEFAULT_HOLD = 100


def parse(raw: str) -> Sequence | None:
    return parse_command(raw, PREFIX, DEFAULT_HOLD)


def single_button(seq: Sequence) -> ButtonInput:
    """Unwrap a single-button sequence for convenience."""
    assert len(seq.steps) == 1
    step = seq.steps[0]
    assert isinstance(step, ChordStep)
    assert len(step.buttons) == 1
    assert len(step.axes) == 0
    return step.buttons[0]


# ── Backwards compatibility: single button presses ───────────────────────────


class TestSingleButton:
    def test_lowercase_a(self):
        result = parse("!a")
        assert result is not None
        btn = single_button(result)
        assert btn == ButtonInput(Button.A, DEFAULT_HOLD)

    def test_uppercase_A(self):
        result = parse("!A")
        assert result is not None
        btn = single_button(result)
        assert btn == ButtonInput(Button.A, DEFAULT_HOLD)

    def test_mixed_case(self):
        result = parse("!Start")
        assert result is not None
        btn = single_button(result)
        assert btn == ButtonInput(Button.START, DEFAULT_HOLD)

    def test_all_buttons(self):
        for b in Button:
            result = parse(f"!{b.value}")
            assert result is not None, f"Expected result for !{b.value}"
            btn = single_button(result)
            assert btn.button == b

    def test_hold_ms_is_default(self):
        result = parse("!b")
        assert result is not None
        assert single_button(result).hold_ms == DEFAULT_HOLD

    def test_with_trailing_whitespace(self):
        result = parse("!x  ")
        assert result is not None
        assert single_button(result).button == Button.X


# ── Invalid commands ─────────────────────────────────────────────────────────


class TestInvalidCommands:
    def test_unknown_button(self):
        assert parse("!zzz") is None

    def test_no_prefix(self):
        assert parse("a") is None

    def test_empty_after_prefix(self):
        assert parse("!") is None

    def test_empty_string(self):
        assert parse("") is None

    def test_wrong_prefix(self):
        assert parse_command("?a", "!", DEFAULT_HOLD) is None

    def test_custom_prefix(self):
        result = parse_command("?a", "?", DEFAULT_HOLD)
        assert result is not None
        assert single_button(result).button == Button.A

    def test_unknown_in_sequence_rejects_all(self):
        assert parse("!a zzz b") is None

    def test_unknown_in_chord_rejects_all(self):
        assert parse("!a+zzz") is None

    def test_empty_chord_element(self):
        assert parse("!a+") is None
        assert parse("!+a") is None


# ── Custom hold durations ────────────────────────────────────────────────────


class TestDuration:
    def test_button_with_duration(self):
        result = parse("!a:500")
        assert result is not None
        btn = single_button(result)
        assert btn.button == Button.A
        assert btn.hold_ms == 500

    def test_zero_duration_rejected(self):
        assert parse("!a:0") is None

    def test_negative_duration_rejected(self):
        assert parse("!a:-100") is None

    def test_non_integer_duration_rejected(self):
        assert parse("!a:abc") is None

    def test_exceeds_max_hold(self):
        set_limits(max_hold_ms=1000)
        assert parse("!a:1001") is None
        result = parse("!a:1000")
        assert result is not None
        set_limits(max_hold_ms=5000)  # restore


# ── Chords (simultaneous buttons) ───────────────────────────────────────────


class TestChords:
    def test_two_buttons(self):
        result = parse("!a+b")
        assert result is not None
        assert len(result.steps) == 1
        step = result.steps[0]
        assert isinstance(step, ChordStep)
        assert len(step.buttons) == 2
        buttons = {b.button for b in step.buttons}
        assert buttons == {Button.A, Button.B}

    def test_three_buttons(self):
        result = parse("!a+b+x")
        assert result is not None
        step = result.steps[0]
        assert isinstance(step, ChordStep)
        assert len(step.buttons) == 3

    def test_chord_with_durations(self):
        result = parse("!a:200+b:500")
        assert result is not None
        step = result.steps[0]
        assert isinstance(step, ChordStep)
        holds = {b.button: b.hold_ms for b in step.buttons}
        assert holds[Button.A] == 200
        assert holds[Button.B] == 500

    def test_chord_with_axis(self):
        result = parse("!a+lx:50")
        assert result is not None
        step = result.steps[0]
        assert isinstance(step, ChordStep)
        assert len(step.buttons) == 1
        assert len(step.axes) == 1
        assert step.axes[0] == AxisInput(Axis.LX, 50)


# ── Sequences ────────────────────────────────────────────────────────────────


class TestSequences:
    def test_two_step_sequence(self):
        result = parse("!down right")
        assert result is not None
        assert len(result.steps) == 2
        step0 = result.steps[0]
        step1 = result.steps[1]
        assert isinstance(step0, ChordStep)
        assert isinstance(step1, ChordStep)
        assert step0.buttons[0].button == Button.DOWN
        assert step1.buttons[0].button == Button.RIGHT

    def test_fighting_game_combo(self):
        result = parse("!down down+right right a")
        assert result is not None
        assert len(result.steps) == 4
        # Step 2 is a chord: down+right
        step2 = result.steps[1]
        assert isinstance(step2, ChordStep)
        assert len(step2.buttons) == 2

    def test_charge_move(self):
        result = parse("!back:2000 right+a")
        assert result is not None
        assert len(result.steps) == 2
        step0 = result.steps[0]
        assert isinstance(step0, ChordStep)
        assert step0.buttons[0].hold_ms == 2000

    def test_sequence_with_wait(self):
        result = parse("!a ~200 b")
        assert result is not None
        assert len(result.steps) == 3
        assert isinstance(result.steps[0], ChordStep)
        assert isinstance(result.steps[1], WaitStep)
        assert result.steps[1].wait_ms == 200
        assert isinstance(result.steps[2], ChordStep)


# ── Waits ────────────────────────────────────────────────────────────────────


class TestWaits:
    def test_wait_step(self):
        result = parse("!a ~100 b")
        assert result is not None
        wait = result.steps[1]
        assert isinstance(wait, WaitStep)
        assert wait.wait_ms == 100

    def test_zero_wait_rejected(self):
        assert parse("!a ~0 b") is None

    def test_negative_wait_rejected(self):
        assert parse("!a ~-50 b") is None

    def test_non_integer_wait_rejected(self):
        assert parse("!a ~abc b") is None


# ── Analog sticks ────────────────────────────────────────────────────────────


class TestAxes:
    def test_single_axis(self):
        result = parse("!lx:50")
        assert result is not None
        step = result.steps[0]
        assert isinstance(step, ChordStep)
        assert len(step.axes) == 1
        assert step.axes[0] == AxisInput(Axis.LX, 50)
        assert len(step.buttons) == 0

    def test_two_axes(self):
        result = parse("!lx:50+ly:-50")
        assert result is not None
        step = result.steps[0]
        assert isinstance(step, ChordStep)
        assert len(step.axes) == 2

    def test_all_axes(self):
        for axis in Axis:
            result = parse(f"!{axis.value}:50")
            assert result is not None

    def test_negative_value(self):
        result = parse("!ly:-100")
        assert result is not None
        step = result.steps[0]
        assert isinstance(step, ChordStep)
        assert step.axes[0].value == -100

    def test_zero_value(self):
        result = parse("!lx:0")
        assert result is not None

    def test_out_of_range_positive(self):
        assert parse("!lx:101") is None

    def test_out_of_range_negative(self):
        assert parse("!lx:-101") is None

    def test_axis_with_button(self):
        result = parse("!lx:50+a")
        assert result is not None
        step = result.steps[0]
        assert isinstance(step, ChordStep)
        assert len(step.buttons) == 1
        assert len(step.axes) == 1


# ── Validation limits ────────────────────────────────────────────────────────


class TestLimits:
    def test_too_many_steps(self):
        set_limits(max_steps=3)
        assert parse("!a b x y") is None
        result = parse("!a b x")
        assert result is not None
        set_limits(max_steps=20)  # restore

    def test_total_duration_exceeded(self):
        set_limits(max_total_ms=500)
        assert parse("!a:300 b:300") is None
        result = parse("!a:200 b:200")
        assert result is not None
        set_limits(max_total_ms=10000)  # restore


# ── Canonical form ───────────────────────────────────────────────────────────


class TestCanonical:
    def test_single_button(self):
        result = parse("!a")
        assert result is not None
        assert result.canonical == f"a:{DEFAULT_HOLD}"

    def test_chord_sorted(self):
        r1 = parse("!b+a")
        r2 = parse("!a+b")
        assert r1 is not None and r2 is not None
        assert r1.canonical == r2.canonical

    def test_sequence_canonical(self):
        result = parse("!down right a")
        assert result is not None
        assert "down" in result.canonical
        assert "right" in result.canonical
        assert "a" in result.canonical

    def test_wait_in_canonical(self):
        result = parse("!a ~200 b")
        assert result is not None
        assert "~200" in result.canonical


# ── Timesharing truncation ───────────────────────────────────────────────────


class TestTimesharing:
    def test_max_keypresses_truncates(self):
        result = parse_command("!a b x y", PREFIX, DEFAULT_HOLD, max_keypresses=2)
        assert result is not None
        assert len(result.steps) == 2  # truncated after 2 keypresses

    def test_max_keypresses_exact(self):
        result = parse_command("!a b", PREFIX, DEFAULT_HOLD, max_keypresses=2)
        assert result is not None
        assert len(result.steps) == 2  # exactly at the limit

    def test_max_keypresses_zero_unlimited(self):
        result = parse_command("!a b x y", PREFIX, DEFAULT_HOLD, max_keypresses=0)
        assert result is not None
        assert len(result.steps) == 4

    def test_max_keypresses_chord_counts_all_buttons(self):
        # a+b is 2 keypresses in one step
        result = parse_command("!a+b x", PREFIX, DEFAULT_HOLD, max_keypresses=2)
        assert result is not None
        assert len(result.steps) == 1  # a+b used both keypresses, x truncated

    def test_max_keypresses_waits_not_counted(self):
        result = parse_command("!a ~100 b ~100 x", PREFIX, DEFAULT_HOLD, max_keypresses=2)
        assert result is not None
        # a (1 key), ~100 (0 keys), b (1 key) = 2 keys, ~100 (0 keys) passes, x truncated
        assert len(result.steps) == 4

    def test_max_command_duration_truncates(self):
        result = parse_command(
            "!a:300 b:300 x:300", PREFIX, DEFAULT_HOLD, max_command_duration_ms=500
        )
        assert result is not None
        # 300 + 300 = 600 > 500, so only first step fits
        assert len(result.steps) == 1

    def test_max_command_duration_includes_waits(self):
        result = parse_command("!a ~400 b", PREFIX, DEFAULT_HOLD, max_command_duration_ms=300)
        assert result is not None
        # a = 100ms, ~400 would push to 500ms > 300, so truncated after a
        assert len(result.steps) == 1

    def test_both_limits_first_hit_wins(self):
        # Duration limit hit first: a:500 = 500ms > 300ms limit
        result = parse_command(
            "!a:500 b c", PREFIX, DEFAULT_HOLD, max_keypresses=10, max_command_duration_ms=300
        )
        assert result is None  # first step already exceeds duration

    def test_single_command_exceeding_all_returns_none(self):
        # If even the first step exceeds the limit, nothing to truncate
        result = parse_command("!a+b+x", PREFIX, DEFAULT_HOLD, max_keypresses=2)
        assert result is None
