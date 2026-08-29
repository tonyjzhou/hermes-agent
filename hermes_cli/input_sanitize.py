"""Sanitize user prompt text leaked from terminal / paste control sequences."""

from __future__ import annotations

import re

_BRACKETED_PASTE_BOUNDARY_START = re.compile(r"(^|[\s\n>:\]\)])\[200~")
_BRACKETED_PASTE_BOUNDARY_END = re.compile(r"\[201~(?=$|[\s\n<\[\(\):;.,!?])")
_BRACKETED_PASTE_DEGRADED_START = re.compile(r"(^|[\s\n>:\]\)])00~")
_BRACKETED_PASTE_DEGRADED_END = re.compile(r"01~(?=$|[\s\n<\[\(\):;.,!?])")

# Leaked xterm modifyOtherKeys (ESC[27;mod;cp~ / ^[[27;mod;cp~ / [27;mod;cp~)
_MOK_RE = re.compile(r"(?:\x1b\[|\^\[\[|(?<=[^\w\d])\[|^\[)27;(\d+);(\d+)[~u]")
# Leaked Kitty CSI-u (ESC[cp;modu / ^[[cp;modu / [cp;modu)
_CSIU_RE = re.compile(r"(?:\x1b\[|\^\[\[|(?<=[^\w\d])\[|^\[)(\d+)(?:;(\d+))?u")
# Leaked terminal focus reports (FocusIn / FocusOut)
_FOCUS_REPORT_RE = re.compile(r"(?:\x1b\[|\^\[\[)[IO]")
# Leaked non-character CSI sequences (e.g. cursor nav under lock bits ^[[1;129B, etc.)
_LEAKED_CSI_OTHER_RE = re.compile(r"(?:\x1b\[|\^\[\[)\d+(?:;\d+)?[~A-Za-z]")

# Corruption signature from desktop bracketed-paste leaks (#62557).
_DESKTOP_PASTE_ARTIFACT = "~[[e"


def _decode_mok_match(m: re.Match[str]) -> str:
    mod = int(m.group(1))
    cp = int(m.group(2))
    if mod == 2:  # Shift
        if (65 <= cp <= 90) or (97 <= cp <= 122):
            return chr(cp).upper()
        if 32 <= cp <= 126 or cp >= 160:
            return chr(cp)
        return ""
    elif mod in (0, 1):  # No modifier / standard key
        if 32 <= cp <= 126 or cp >= 160:
            return chr(cp)
        return ""
    return ""


def _decode_csiu_match(m: re.Match[str]) -> str:
    cp = int(m.group(1))
    mod = int(m.group(2)) if m.group(2) is not None else 1
    # Kitty Private Use Area functional keys (keypad, etc.)
    if 57358 <= cp <= 57455:
        if 57399 <= cp <= 57408:
            return str(cp - 57399)
        kp_map = {
            57409: ".",
            57410: "/",
            57411: "*",
            57412: "-",
            57413: "+",
            57415: "=",
            57416: ",",
        }
        return kp_map.get(cp, "")
    base_mod = mod % 64 if mod >= 64 else mod
    if base_mod == 2:  # Shift
        if (65 <= cp <= 90) or (97 <= cp <= 122):
            return chr(cp).upper()
        if 32 <= cp <= 126 or cp >= 160:
            return chr(cp)
        return ""
    elif base_mod in (0, 1):
        if 32 <= cp <= 126 or cp >= 160:
            return chr(cp)
        return ""
    return ""


def strip_or_decode_leaked_xterm_sequences(text: str) -> str:
    """Decode or strip leaked xterm modifyOtherKeys and Kitty CSI-u escape sequences.

    When terminal extended key modes (modifyOtherKeys level 2 or Kitty protocol)
    leak into the input buffer, character keys (e.g. Shift+Q as ^[[27;2;81~)
    are decoded to their intended character ('Q'), while control/noise sequences
    (e.g. Ctrl+C as ^[[27;5;99~, focus reports ^[[I/^[[O) are safely stripped.
    """
    if not text:
        return text

    text = _MOK_RE.sub(_decode_mok_match, text)
    text = _CSIU_RE.sub(_decode_csiu_match, text)
    text = _FOCUS_REPORT_RE.sub("", text)
    text = _LEAKED_CSI_OTHER_RE.sub("", text)
    return text


def strip_leaked_bracketed_paste_wrappers(text: str) -> str:
    """Strip leaked bracketed-paste wrapper markers from user-visible text.

    Defensive normalization for cases where terminal/prompt_toolkit parsing
    fails and bracketed-paste markers end up in the buffer as literal text.

    Canonical wrappers are stripped unconditionally. Degraded visible forms like
    ``[200~`` / ``[201~`` and ``00~`` / ``01~`` are removed only at boundaries
    so embedded literals such as ``literal[200~tag`` stay intact.
    """
    if not text:
        return text

    text = (
        text.replace("\x1b[200~", "")
        .replace("\x1b[201~", "")
        .replace("^[[200~", "")
        .replace("^[[201~", "")
    )
    text = _BRACKETED_PASTE_BOUNDARY_START.sub(r"\1", text)
    text = _BRACKETED_PASTE_BOUNDARY_END.sub("", text)
    text = _BRACKETED_PASTE_DEGRADED_START.sub(r"\1", text)
    text = _BRACKETED_PASTE_DEGRADED_END.sub("", text)
    return text


def collapse_repeated_input_artifacts(text: str, min_repeats: int = 4) -> str:
    """Drop a trailing run of the desktop ~[[e corruption signature (#62557)."""
    if not text:
        return text

    marker = _DESKTOP_PASTE_ARTIFACT
    index = len(text)
    repeat_count = 0
    while index >= len(marker) and text[index - len(marker) : index] == marker:
        repeat_count += 1
        index -= len(marker)

    if repeat_count < min_repeats:
        return text

    start = index
    if start >= 2 and text[start - 2 : start] == "[e":
        start -= 2
    elif start >= 1 and text[start - 1] == "[":
        start -= 1
    return text[:start]


def sanitize_user_prompt_text(text: str) -> str:
    """Normalize user-authored prompt text before persistence or model input."""
    if not isinstance(text, str) or not text:
        return text
    cleaned = strip_or_decode_leaked_xterm_sequences(text)
    cleaned = strip_leaked_bracketed_paste_wrappers(cleaned)
    return collapse_repeated_input_artifacts(cleaned)
