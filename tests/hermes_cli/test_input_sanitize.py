"""Tests for shared user prompt input sanitization."""

from hermes_cli.input_sanitize import (
    collapse_repeated_input_artifacts,
    sanitize_user_prompt_text,
    strip_leaked_bracketed_paste_wrappers,
    strip_or_decode_leaked_xterm_sequences,
)


class TestStripOrDecodeLeakedXtermSequences:
    def test_decode_modify_other_keys_uppercase(self):
        assert strip_or_decode_leaked_xterm_sequences("^[[27;2;81~") == "Q"
        assert strip_or_decode_leaked_xterm_sequences("\x1b[27;2;81~") == "Q"
        assert strip_or_decode_leaked_xterm_sequences("[27;2;81~") == "Q"
        assert strip_or_decode_leaked_xterm_sequences("^[[27;2;113~") == "Q"
        assert strip_or_decode_leaked_xterm_sequences("^[[27;2;65~") == "A"
        assert strip_or_decode_leaked_xterm_sequences("^[[27;2;97~") == "A"

    def test_decode_kitty_csiu_uppercase(self):
        assert strip_or_decode_leaked_xterm_sequences("^[[81;2u") == "Q"
        assert strip_or_decode_leaked_xterm_sequences("^[[113;2u") == "Q"
        assert strip_or_decode_leaked_xterm_sequences("^[[81;130u") == "Q"

    def test_strip_control_and_focus_sequences(self):
        assert strip_or_decode_leaked_xterm_sequences("^[[27;5;99~") == ""
        assert strip_or_decode_leaked_xterm_sequences("^[[I") == ""
        assert strip_or_decode_leaked_xterm_sequences("^[[O") == ""
        assert strip_or_decode_leaked_xterm_sequences("^[[1;129B") == ""
        assert strip_or_decode_leaked_xterm_sequences("^[[3;9~") == ""

    def test_inline_decoded_word(self):
        assert (
            strip_or_decode_leaked_xterm_sequences("Hello ^[[27;2;81~uality World")
            == "Hello Quality World"
        )

    def test_preserves_legitimate_brackets(self):
        assert strip_or_decode_leaked_xterm_sequences("[27 items in list]") == "[27 items in list]"
        assert strip_or_decode_leaked_xterm_sequences("matrix[27][2]") == "matrix[27][2]"
        assert strip_or_decode_leaked_xterm_sequences("user input with [brackets]") == "user input with [brackets]"


class TestStripLeakedBracketedPasteWrappers:
    def test_plain_text_unchanged(self):
        assert strip_leaked_bracketed_paste_wrappers("hello world") == "hello world"



    def test_does_not_strip_non_wrapper_bracket_forms_in_normal_text(self):
        text = "literal[200~tag and literal[201~tag should stay"
        assert strip_leaked_bracketed_paste_wrappers(text) == text


class TestCollapseRepeatedInputArtifacts:
    def test_issue_62557_corruption_tail(self):
        prefix = "需要时随时叫我。"
        tail = "[e~[[e" + "~[[e" * 20
        assert collapse_repeated_input_artifacts(prefix + tail) == prefix


    def test_trailing_punctuation_preserved(self):
        assert collapse_repeated_input_artifacts("wait....") == "wait...."


class TestSanitizeUserPromptText:
    def test_combines_wrapper_strip_and_tail_collapse(self):
        prefix = "hello["
        corrupted = prefix + "~[[e" * 8
        assert sanitize_user_prompt_text(corrupted) == "hello"
