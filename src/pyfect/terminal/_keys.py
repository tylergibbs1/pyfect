"""Terminal input as key presses, named as Node's ``readline`` names them
(``emitKeypressEvents``)."""

from __future__ import annotations

import re

from pyfect.terminal._service import Key, UserInput

# ESC [ or ESC O, optional parameters, a final letter or "~".
_SEQUENCE = re.compile(r"\x1b(?:\[|O)([0-9;]*)([A-Za-z~])")

_FINAL_NAMES = {
    "A": "up",
    "B": "down",
    "C": "right",
    "D": "left",
    "E": "clear",
    "F": "end",
    "H": "home",
    "P": "f1",
    "Q": "f2",
    "R": "f3",
    "S": "f4",
}

_TILDE_NAMES = {
    "1": "home",
    "2": "insert",
    "3": "delete",
    "4": "end",
    "5": "pageup",
    "6": "pagedown",
    "7": "home",
    "8": "end",
    "11": "f1",
    "12": "f2",
    "13": "f3",
    "14": "f4",
    "15": "f5",
    "17": "f6",
    "18": "f7",
    "19": "f8",
    "20": "f9",
    "21": "f10",
    "23": "f11",
    "24": "f12",
}

_SINGLE_NAMES = {
    "\r": "return",
    "\n": "enter",
    "\t": "tab",
    "\b": "backspace",
    "\x7f": "backspace",
    "\x1b": "escape",
    " ": "space",
}


def _modifiers(code: int) -> tuple[bool, bool, bool]:
    """``(ctrl, meta, shift)`` from an xterm modifier parameter."""
    bits = max(code - 1, 0)
    return bool(bits & 4), bool(bits & 10), bool(bits & 1)


def _sequence(params: str, final: str) -> Key:
    parts = params.split(";") if params else []
    ctrl, meta, shift = _modifiers(int(parts[1])) if len(parts) > 1 and parts[1] else (False,) * 3
    if final == "~":
        name = _TILDE_NAMES.get(parts[0] if parts else "", "undefined")
    elif final == "Z":
        return Key("tab", shift=True)
    else:
        name = _FINAL_NAMES.get(final, "undefined")
    return Key("" if name == "undefined" else name, ctrl=ctrl, meta=meta, shift=shift)


def _single(char: str, *, meta: bool = False) -> Key:
    if char in _SINGLE_NAMES:
        return Key(_SINGLE_NAMES[char], meta=meta)
    code = ord(char)
    if code < 0x20:
        return Key(chr(code + 0x60), ctrl=True, meta=meta)
    if char.isascii() and char.isalnum():
        return Key(char.lower(), meta=meta, shift=char.isupper())
    return Key("", meta=meta)


def decode(text: str) -> list[UserInput]:
    """The key presses in ``text``. A lone ESC is the escape key; ESC
    before a character is that key with ``meta``."""
    events: list[UserInput] = []
    position = 0
    while position < len(text):
        sequence = _SEQUENCE.match(text, position)
        if sequence is not None:
            events.append(UserInput(None, _sequence(sequence.group(1), sequence.group(2))))
            position = sequence.end()
            continue
        char = text[position]
        if char == "\x1b" and position + 1 < len(text) and text[position + 1] != "\x1b":
            following = text[position + 1]
            events.append(UserInput(following, _single(following, meta=True)))
            position += 2
            continue
        if char == "\r" and text.startswith("\n", position + 1):
            events.append(UserInput("\r\n", Key("return")))
            position += 2
            continue
        events.append(UserInput(char, _single(char)))
        position += 1
    return events
