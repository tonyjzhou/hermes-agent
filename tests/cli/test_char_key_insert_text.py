"""Regression tests: character-valued key aliases must type their character.

``Vt100Parser._call_handler`` builds ``KeyPress(key, insert_text)`` with
``insert_text`` set to the matched *byte sequence*, and prompt_toolkit's
``self-insert`` binding inserts ``event.data`` — not ``event.key``. Every
``ANSI_SEQUENCES`` entry mapped to a literal character was therefore typing
its own escape sequence into the prompt: Shift+A under xterm modifyOtherKeys
(``ESC[27;2;65~``) produced the visible text ``^[[27;2;65~`` instead of ``A``
on every terminal the CLI pushes ``ESC[>4;2m`` to.

``install_char_key_insert_text_patch()`` fixes the data payload at the point
the ``KeyPress`` is built. These tests assert the *inserted text*, which is
what the sibling ``test_modify_other_keys_aliases.py`` suite cannot see: it
compares ``KeyPress.key`` only, so it stayed green throughout the bug.
"""

from __future__ import annotations

import asyncio

import pytest

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import set_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.input import DummyInput
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.input.vt100_parser import Vt100Parser
from prompt_toolkit.key_binding.defaults import load_key_bindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import Layout, Window
from prompt_toolkit.layout.controls import BufferControl
from prompt_toolkit.output import DummyOutput

from hermes_cli.pt_input_extras import (
    install_char_key_insert_text_patch,
    install_cmd_backspace_alias,
    install_ctrl_enter_alias,
    install_modify_other_keys_aliases,
    install_shift_enter_alias,
)


@pytest.fixture(autouse=True)
def _cli_input_stack():
    """Install the same alias stack cli.py installs at startup, then restore
    ANSI_SEQUENCES so the hundreds of mappings don't leak sideways."""
    saved = dict(ANSI_SEQUENCES)
    install_shift_enter_alias()
    install_ctrl_enter_alias()
    install_cmd_backspace_alias()
    install_modify_other_keys_aliases()
    install_char_key_insert_text_patch()
    yield
    ANSI_SEQUENCES.clear()
    ANSI_SEQUENCES.update(saved)
    from prompt_toolkit.input.vt100_parser import _IS_PREFIX_OF_LONGER_MATCH_CACHE
    _IS_PREFIX_OF_LONGER_MATCH_CACHE.clear()


def _keypresses(byte_seq: str) -> list:
    """Feed bytes through the real VT100 parser, return the KeyPress list."""
    out: list = []
    parser = Vt100Parser(out.append)
    for ch in byte_seq:
        parser.feed(ch)
    parser.flush()
    return out


def _typed(byte_seq: str) -> str:
    """The text a real prompt_toolkit buffer ends up with after the terminal
    sends ``byte_seq`` — the full parser → key processor → binding path."""

    async def run() -> str:
        buf = Buffer()
        app = Application(
            layout=Layout(Window(BufferControl(buffer=buf))),
            key_bindings=load_key_bindings(),
            input=DummyInput(),
            output=DummyOutput(),
        )
        with set_app(app):
            app.key_processor.feed_multiple(_keypresses(byte_seq))
            app.key_processor.process_keys()
        return buf.text

    return asyncio.run(run())


# ---------------------------------------------------------------------------
# The reported symptom: uppercase letters under modifyOtherKeys
# ---------------------------------------------------------------------------

LETTERS = [chr(c) for c in range(ord("a"), ord("z") + 1)]


@pytest.mark.parametrize("letter", LETTERS)
def test_shift_letter_types_uppercase_not_the_escape_sequence(letter):
    """Shift+<letter> must type the uppercase character under both protocols
    and both codepoint conventions (xterm reports the shifted codepoint,
    kitty the unshifted one)."""
    upper = letter.upper()
    for seq in (
        f"\x1b[27;2;{ord(upper)}~",  # modifyOtherKeys, shifted codepoint
        f"\x1b[27;2;{ord(letter)}~",  # modifyOtherKeys, unshifted codepoint
        f"\x1b[{ord(letter)};2u",  # kitty CSI-u
    ):
        assert _typed(seq) == upper, (
            f"{seq!r} should type {upper!r}, got {_typed(seq)!r}"
        )


def test_shift_a_does_not_leak_the_raw_sequence():
    """The exact sequence from the bug report must never appear as text."""
    typed = _typed("\x1b[27;2;65~")
    assert "27;2;65" not in typed
    assert typed == "A"


@pytest.mark.parametrize("modifier", [2, 66, 130, 194])
def test_shift_letter_types_uppercase_under_lock_bits(modifier):
    """CapsLock (+64) / NumLock (+128) twins of Shift+letter type uppercase."""
    assert _typed(f"\x1b[97;{modifier}u") == "A"


# ---------------------------------------------------------------------------
# The rest of the character-valued mappings, broken by the same root cause
# ---------------------------------------------------------------------------

def test_shift_space_types_a_space():
    assert _typed("\x1b[27;2;32~") == " "
    assert _typed("\x1b[32;2u") == " "


def test_space_with_lock_bit_types_a_space():
    assert _typed("\x1b[32;129u") == " "


@pytest.mark.parametrize("digit", range(10))
def test_keypad_digits_type_their_digit(digit):
    """Kitty PUA keypad codepoints leaked ``^[[57399u`` instead of typing."""
    assert _typed(f"\x1b[{57399 + digit}u") == str(digit)


@pytest.mark.parametrize(
    "codepoint,expected",
    [(57409, "."), (57410, "/"), (57411, "*"), (57412, "-"), (57413, "+"), (57415, "=")],
)
def test_keypad_operators_type_their_symbol(codepoint, expected):
    assert _typed(f"\x1b[{codepoint}u") == expected


# ---------------------------------------------------------------------------
# The invariant, over the whole table
# ---------------------------------------------------------------------------

def test_every_character_valued_alias_carries_its_character_as_data():
    """Contract: when a sequence resolves to a literal character, the KeyPress
    data payload must BE that character — otherwise self-insert types the
    escape sequence. Swept over the table so a future character-valued
    registration can't reintroduce the bug."""
    char_valued = {
        seq: value
        for seq, value in ANSI_SEQUENCES.items()
        if isinstance(value, str)
        and not isinstance(value, Keys)
        and len(value) == 1
        and seq != value
    }
    assert char_valued, "expected the alias installers to register character keys"

    offenders = []
    for seq, char in char_valued.items():
        for keypress in _keypresses(seq):
            if keypress.key == char and keypress.data != char:
                offenders.append((seq, char, keypress.data))

    assert not offenders, f"aliases typing their escape sequence: {offenders!r}"


# ---------------------------------------------------------------------------
# Nothing else may change
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("char", ["a", "A", "z", "Z", "0", "9", " ", "!", "~"])
def test_plain_characters_are_unaffected(char):
    assert _typed(char) == char


@pytest.mark.parametrize(
    "seq,expected_key",
    [
        ("\x1b[27;5;99~", Keys.ControlC),
        ("\x1b[99;5u", Keys.ControlC),
        ("\x1b[27;5;117~", Keys.ControlU),
        ("\x1b[27;2;9~", Keys.BackTab),
        ("\x1b[27u", Keys.Escape),
    ],
)
def test_keys_valued_aliases_keep_their_key(seq, expected_key):
    """``Keys.*`` entries dispatch on the key — the patch only touches the
    data payload and must not disturb which key is reported."""
    assert [kp.key for kp in _keypresses(seq)] == [expected_key]


@pytest.mark.parametrize("letter", LETTERS)
def test_ctrl_letter_extended_encodings_match_the_legacy_byte(letter):
    """Contract: an extended encoding must be indistinguishable from the raw
    control byte, payload included. Ctrl+Z has no default binding, so it falls
    through to self-insert — legacy typed an invisible ``\\x1a`` while
    ``ESC[27;5;122~`` typed visible junk into the prompt."""
    legacy = chr(ord(letter) - ord("a") + 1)
    expected = _typed(legacy)
    for seq in (f"\x1b[27;5;{ord(letter)}~", f"\x1b[{ord(letter)};5u"):
        assert _typed(seq) == expected, (
            f"Ctrl+{letter} ({seq!r}) typed {_typed(seq)!r}, "
            f"legacy {legacy!r} typed {expected!r}"
        )


def test_no_control_combo_leaks_an_escape_sequence():
    """No Ctrl/Alt combo may ever put a CSI sequence in the prompt buffer."""
    offenders = []
    for letter in LETTERS:
        for seq in (
            f"\x1b[27;5;{ord(letter)}~",
            f"\x1b[{ord(letter)};5u",
            f"\x1b[27;3;{ord(letter)}~",
            f"\x1b[{ord(letter)};3u",
        ):
            typed = _typed(seq)
            if "\x1b[" in typed:
                offenders.append((seq, typed))
    assert not offenders, f"combos leaking their escape sequence: {offenders!r}"


def test_patch_is_idempotent():
    assert install_char_key_insert_text_patch() == 0
