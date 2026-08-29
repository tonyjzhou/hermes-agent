"""Comprehensive test suite for xterm modifyOtherKeys and Kitty CSI-u escape sequence sanitization.

Verifies that:
1. All uppercase letters (A-Z) under Shift (modifier 2) are decoded from xterm modifyOtherKeys
   and Kitty CSI-u formats regardless of escape prefix (\\x1b[, ^[[, [).
2. Unmodified printable keys are decoded accurately.
3. Control sequences (Ctrl+key, Alt+key, Super+key) and terminal noise (focus reports,
   navigation keys under lock bits) are cleanly stripped.
4. Embedded sequences in natural sentences and mixed with bracketed paste are properly handled.
5. Normal bracketed text, array indices, and markdown/code syntax remain untouched.
"""

from __future__ import annotations

import pytest

from hermes_cli.input_sanitize import (
    sanitize_user_prompt_text,
    strip_or_decode_leaked_xterm_sequences,
)


class TestModifyOtherKeysAlphabetDecoding:
    """Verify all 26 English letters (A-Z) decode correctly under Shift (modifier 2)."""

    @pytest.mark.parametrize("char_code", range(ord("A"), ord("Z") + 1))
    def test_uppercase_codepoints_modify_other_keys(self, char_code: int):
        expected = chr(char_code)
        # ^[[27;2;CP~ caret format
        assert strip_or_decode_leaked_xterm_sequences(f"^[[27;2;{char_code}~") == expected
        # \x1b[27;2;CP~ escape format
        assert strip_or_decode_leaked_xterm_sequences(f"\x1b[27;2;{char_code}~") == expected
        # [27;2;CP~ boundary format
        assert strip_or_decode_leaked_xterm_sequences(f"[{27};2;{char_code}~") == expected

    @pytest.mark.parametrize("char_code", range(ord("a"), ord("z") + 1))
    def test_lowercase_codepoints_with_shift_modifier(self, char_code: int):
        expected = chr(char_code).upper()
        # Emitted when terminal sends unshifted codepoint with Shift modifier bit
        assert strip_or_decode_leaked_xterm_sequences(f"^[[27;2;{char_code}~") == expected
        assert strip_or_decode_leaked_xterm_sequences(f"\x1b[27;2;{char_code}~") == expected
        assert strip_or_decode_leaked_xterm_sequences(f"[{27};2;{char_code}~") == expected


class TestKittyCsiUAlphabetDecoding:
    """Verify Kitty CSI-u protocol decoding for uppercase characters."""

    @pytest.mark.parametrize("char_code", range(ord("A"), ord("Z") + 1))
    def test_kitty_csiu_uppercase_and_lock_variants(self, char_code: int):
        expected = chr(char_code)
        # Shift modifier = 2
        assert strip_or_decode_leaked_xterm_sequences(f"^[[{char_code};2u") == expected
        assert strip_or_decode_leaked_xterm_sequences(f"\x1b[{char_code};2u") == expected

        # Shift with CapsLock bit (2 + 64 = 66)
        assert strip_or_decode_leaked_xterm_sequences(f"^[[{char_code};66u") == expected
        # Shift with NumLock bit (2 + 128 = 130)
        assert strip_or_decode_leaked_xterm_sequences(f"^[[{char_code};130u") == expected
        # Shift with both lock bits (2 + 192 = 194)
        assert strip_or_decode_leaked_xterm_sequences(f"^[[{char_code};194u") == expected


class TestKittyKeypadAndFunctionalKeys:
    """Verify Kitty PUA functional keypad and operator keys."""

    def test_keypad_digits(self):
        for digit in range(10):
            pua_code = 57399 + digit
            assert strip_or_decode_leaked_xterm_sequences(f"^[[{pua_code}u") == str(digit)
            assert strip_or_decode_leaked_xterm_sequences(f"\x1b[{pua_code}u") == str(digit)

    def test_keypad_operators(self):
        operators = {
            57409: ".",
            57410: "/",
            57411: "*",
            57412: "-",
            57413: "+",
            57415: "=",
            57416: ",",
        }
        for pua_code, expected_char in operators.items():
            assert strip_or_decode_leaked_xterm_sequences(f"^[[{pua_code}u") == expected_char


class TestStripTerminalNoiseAndControlSequences:
    """Verify non-printable control combinations and terminal reports are stripped."""

    def test_ctrl_key_leaks_stripped(self):
        # Ctrl+C (^[[27;5;99~), Ctrl+A (^[[27;5;97~), Ctrl+Z (^[[27;5;122~)
        assert strip_or_decode_leaked_xterm_sequences("^[[27;5;99~") == ""
        assert strip_or_decode_leaked_xterm_sequences("\x1b[27;5;97~") == ""
        assert strip_or_decode_leaked_xterm_sequences("[27;5;122~") == ""

    def test_alt_key_leaks_stripped(self):
        # Alt+A (^[[27;3;97~)
        assert strip_or_decode_leaked_xterm_sequences("^[[27;3;97~") == ""
        assert strip_or_decode_leaked_xterm_sequences("\x1b[27;3;97~") == ""

    def test_focus_events_stripped(self):
        # Focus In (^[[I) / Focus Out (^[[O)
        assert strip_or_decode_leaked_xterm_sequences("^[[I") == ""
        assert strip_or_decode_leaked_xterm_sequences("^[[O") == ""
        assert strip_or_decode_leaked_xterm_sequences("\x1b[I") == ""
        assert strip_or_decode_leaked_xterm_sequences("\x1b[O") == ""

    def test_navigation_and_functional_pua_keys_stripped(self):
        # Esc key (^[[27u), Lock keys, F13-F24, cursor nav under lock bits
        assert strip_or_decode_leaked_xterm_sequences("^[[27u") == ""
        assert strip_or_decode_leaked_xterm_sequences("^[[1;129B") == ""
        assert strip_or_decode_leaked_xterm_sequences("^[[3;9~") == ""
        assert strip_or_decode_leaked_xterm_sequences("^[[57358u") == ""


class TestSentenceAndContextualDecoding:
    """Verify escape sequence decoding inside realistic conversational text."""

    def test_consecutive_capital_letters(self):
        # "NASDAQ" where each letter was typed with Shift
        raw = (
            "^[[27;2;78~"   # N
            "^[[27;2;65~"   # A
            "^[[27;2;83~"   # S
            "^[[27;2;68~"   # D
            "^[[27;2;65~"   # A
            "^[[27;2;81~"   # Q
        )
        assert strip_or_decode_leaked_xterm_sequences(raw) == "NASDAQ"

    def test_mixed_sentence_with_uppercase_and_noise(self):
        prompt = (
            "^[[I"                          # Focus In noise
            "Analyze ^[[27;2;84~SLA and "   # TSLA (T with shift)
            "^[[27;2;65~APL balance sheet"  # AAPL (A with shift)
            "^[[O"                          # Focus Out noise
        )
        assert strip_or_decode_leaked_xterm_sequences(prompt) == "Analyze TSLA and AAPL balance sheet"

    def test_user_query_reported_in_bug(self):
        # Letter Q becoming ^[[27;2;81~
        assert strip_or_decode_leaked_xterm_sequences("^[[27;2;81~") == "Q"
        assert strip_or_decode_leaked_xterm_sequences("investor > ^[[27;2;81~") == "investor > Q"


class TestFullPromptSanitizerIntegration:
    """Verify sanitize_user_prompt_text combines xterm decoding, bracketed paste, and artifact collapse."""

    def test_combines_xterm_decoding_and_bracketed_paste(self):
        raw = "[200~Explain ^[[27;2;81~uantitative Easing[201~"
        assert sanitize_user_prompt_text(raw) == "Explain Quantitative Easing"

    def test_combines_xterm_decoding_and_corruption_collapse(self):
        raw = "Analyze ^[[27;2;78~VDA~[[e~[[e~[[e~[[e"
        assert sanitize_user_prompt_text(raw) == "Analyze NVDA"


class TestFalsePositivePreservation:
    """Ensure legitimate user input, brackets, numbers, and syntax are never corrupted."""

    @pytest.mark.parametrize(
        "safe_input",
        [
            "[27 items in list]",
            "matrix[27][2]",
            "query[27;2]",
            "literal[200~tag",
            "regex: r'\\[27;\\d+\\]'",
            "See [Section 27.2](https://example.com)",
            "Values between [0, 100]",
            "",
            "Plain text without any brackets or escapes.",
        ],
    )
    def test_preserves_legitimate_syntax(self, safe_input: str):
        assert strip_or_decode_leaked_xterm_sequences(safe_input) == safe_input
        assert sanitize_user_prompt_text(safe_input) == safe_input
