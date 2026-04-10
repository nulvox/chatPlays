"""Tests for parser.py."""

from parser import Button, ButtonInput, parse_command

PREFIX = "!"
DEFAULT_HOLD = 100


def parse(raw: str) -> ButtonInput | None:
    return parse_command(raw, PREFIX, DEFAULT_HOLD)


class TestValidButtons:
    def test_lowercase_a(self):
        result = parse("!a")
        assert result == ButtonInput(Button.A, DEFAULT_HOLD)

    def test_uppercase_A(self):
        result = parse("!A")
        assert result == ButtonInput(Button.A, DEFAULT_HOLD)

    def test_mixed_case(self):
        result = parse("!Start")
        assert result == ButtonInput(Button.START, DEFAULT_HOLD)

    def test_all_buttons(self):
        for btn in Button:
            result = parse(f"!{btn.value}")
            assert result is not None, f"Expected result for !{btn.value}"
            assert result.button == btn

    def test_hold_ms_is_default(self):
        result = parse("!b")
        assert result is not None
        assert result.hold_ms == DEFAULT_HOLD

    def test_with_trailing_whitespace(self):
        result = parse("!x  ")
        assert result == ButtonInput(Button.X, DEFAULT_HOLD)


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
        result = parse_command("?a", "!", DEFAULT_HOLD)
        assert result is None

    def test_custom_prefix(self):
        result = parse_command("?a", "?", DEFAULT_HOLD)
        assert result == ButtonInput(Button.A, DEFAULT_HOLD)


class TestPhase2Stub:
    """Phase 2: !<button> <duration> — currently treated as single press."""

    def test_button_with_duration_returns_result(self):
        # Phase 2 stub: parser accepts it but ignores duration
        result = parse("!a 500")
        assert result is not None
        assert result.button == Button.A
        assert result.hold_ms == DEFAULT_HOLD  # duration not yet parsed


class TestPhase3Stub:
    """Phase 3: multi-token sequences — currently dropped."""

    def test_sequence_returns_none(self):
        # Phase 3 stub: sequences are not yet supported
        assert parse("!up up down down") is None

    def test_three_part_sequence_returns_none(self):
        assert parse("!a b x") is None
