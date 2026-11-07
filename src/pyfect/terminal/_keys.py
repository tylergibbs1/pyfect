"""Terminal input as key presses, as Node's ``readline`` reads them
(``emitKeypressEvents``, whose ``emitKeys`` generator this ports).

``KeyDecoder`` keeps a sequence that a read cut short until the next read
finishes it, as the generator does. A read ending in ESC may be the start
of a sequence or the escape key: after ``ESCAPE_CODE_TIMEOUT`` seconds with
no more input, ``timeout`` decides it is the key (Effect's terminal makes
its readline interface with ``escapeCodeTimeout: 50``).
"""

from __future__ import annotations

import re
from collections.abc import Generator

from pyfect.terminal._service import Key, UserInput

ESCAPE_CODE_TIMEOUT = 0.05

_ESC = "\x1b"
_TIMED_OUT = ""
"""What the timeout feeds the parser, as Node's ``next('')``."""

_TILDE_CODE = re.compile(r"(?:(\d\d?)(?:;(\d))?([~^$])|(\d{3}~))", re.ASCII)
_LETTER_CODE = re.compile(r"((\d;)?(\d))?([A-Za-z])", re.ASCII)
_ALNUM = re.compile(r"[0-9A-Za-z]")

# Node's ``switch (code)``: the name and the modifier the code itself adds.
_CODES: dict[str, tuple[str, str | None]] = {
    "[P": ("f1", None),
    "[Q": ("f2", None),
    "[R": ("f3", None),
    "[S": ("f4", None),
    "OP": ("f1", None),
    "OQ": ("f2", None),
    "OR": ("f3", None),
    "OS": ("f4", None),
    "[11~": ("f1", None),
    "[12~": ("f2", None),
    "[13~": ("f3", None),
    "[14~": ("f4", None),
    "[200~": ("paste-start", None),
    "[201~": ("paste-end", None),
    "[[A": ("f1", None),
    "[[B": ("f2", None),
    "[[C": ("f3", None),
    "[[D": ("f4", None),
    "[[E": ("f5", None),
    "[15~": ("f5", None),
    "[17~": ("f6", None),
    "[18~": ("f7", None),
    "[19~": ("f8", None),
    "[20~": ("f9", None),
    "[21~": ("f10", None),
    "[23~": ("f11", None),
    "[24~": ("f12", None),
    "[A": ("up", None),
    "[B": ("down", None),
    "[C": ("right", None),
    "[D": ("left", None),
    "[E": ("clear", None),
    "[F": ("end", None),
    "[H": ("home", None),
    "OA": ("up", None),
    "OB": ("down", None),
    "OC": ("right", None),
    "OD": ("left", None),
    "OE": ("clear", None),
    "OF": ("end", None),
    "OH": ("home", None),
    "[1~": ("home", None),
    "[2~": ("insert", None),
    "[3~": ("delete", None),
    "[4~": ("end", None),
    "[5~": ("pageup", None),
    "[6~": ("pagedown", None),
    "[[5~": ("pageup", None),
    "[[6~": ("pagedown", None),
    "[7~": ("home", None),
    "[8~": ("end", None),
    "[a": ("up", "shift"),
    "[b": ("down", "shift"),
    "[c": ("right", "shift"),
    "[d": ("left", "shift"),
    "[e": ("clear", "shift"),
    "[2$": ("insert", "shift"),
    "[3$": ("delete", "shift"),
    "[5$": ("pageup", "shift"),
    "[6$": ("pagedown", "shift"),
    "[7$": ("home", "shift"),
    "[8$": ("end", "shift"),
    "Oa": ("up", "ctrl"),
    "Ob": ("down", "ctrl"),
    "Oc": ("right", "ctrl"),
    "Od": ("left", "ctrl"),
    "Oe": ("clear", "ctrl"),
    "[2^": ("insert", "ctrl"),
    "[3^": ("delete", "ctrl"),
    "[5^": ("pageup", "ctrl"),
    "[6^": ("pagedown", "ctrl"),
    "[7^": ("home", "ctrl"),
    "[8^": ("end", "ctrl"),
    "[Z": ("tab", "shift"),
}

_SINGLE_NAMES = {
    "\r": "return",
    "\n": "enter",
    "\t": "tab",
    "\b": "backspace",
    "\x7f": "backspace",
    _ESC: "escape",
    " ": "space",
}

type _Parser = Generator[None, str]


def _digit(ch: str) -> bool:
    return "0" <= ch <= "9"


def _sequence_key(code: str, modifier: int) -> Key:
    """The key of an ANSI sequence's ``code`` (``"[A"``, ``"[24~"``) with an
    xterm ``modifier`` (its parameter minus one)."""
    name, added = _CODES.get(code, ("undefined", None))
    return Key(
        name,
        ctrl=bool(modifier & 4) or added == "ctrl",
        meta=bool(modifier & 10),
        shift=bool(modifier & 1) or added == "shift",
    )


def _char_key(ch: str, *, escaped: bool) -> Key | None:
    """The key of one character, ESC-prefixed when ``escaped``; ``None``
    where Node leaves the name undefined (Effect's ``""``)."""
    if ch in _SINGLE_NAMES:
        return Key(_SINGLE_NAMES[ch], meta=escaped)
    if not escaped and ch <= "\x1a":
        return Key(chr(ord(ch) + ord("a") - 1), ctrl=True)
    if _ALNUM.fullmatch(ch):
        return Key(ch.lower(), meta=escaped, shift="A" <= ch <= "Z")
    if escaped:
        # ESC then a character with no name, or nothing before the timeout.
        return Key("escape" if ch == _TIMED_OUT else "", meta=True)
    return None


class KeyDecoder:
    """Key presses from text read in pieces. ``feed`` each piece; when
    ``escape_pending`` holds after it and no more input comes within
    ``ESCAPE_CODE_TIMEOUT``, call ``timeout``."""

    __slots__ = ("_events", "_parser", "escape_pending")

    def __init__(self) -> None:
        self._events: list[UserInput] = []
        self._parser = self._parse()
        next(self._parser)
        self.escape_pending = False

    def feed(self, text: str) -> list[UserInput]:
        for ch in text:
            self._parser.send(ch)
        if text:
            self.escape_pending = text[-1] == _ESC
        return self._take()

    def timeout(self) -> list[UserInput]:
        """No input followed the trailing ESC: finish what it started."""
        self.escape_pending = False
        self._parser.send(_TIMED_OUT)
        return self._take()

    def _take(self) -> list[UserInput]:
        events, self._events = self._events, []
        return events

    def _parse(self) -> _Parser:
        while True:
            ch = yield
            if ch == _TIMED_OUT:
                continue  # The trailing ESC already ended a sequence.
            s = ch
            escaped = False
            if ch == _ESC:
                escaped = True
                ch = yield
                s += ch
                if ch == _ESC:
                    ch = yield
                    s += ch
            if escaped and ch in ("O", "["):
                s, key = yield from _sequence(s, ch)
            else:
                key = _char_key(ch, escaped=escaped)
            if s and (key is not None or escaped):
                self._events.append(UserInput(None if escaped else s, key or Key("")))
            elif len(s) == 1:
                self._events.append(UserInput(s, key or Key("")))
            # An unrecognized or broken sequence gives no key press.


def _sequence(s: str, ch: str) -> Generator[None, str, tuple[str, Key]]:
    """Read the rest of an ANSI sequence begun by ``s`` (ending in ``ch``,
    ``"O"`` or ``"["``): the whole sequence and its key."""
    code = ch
    if ch == "O":
        modifier = 0
        ch = yield
        s += ch
        if _digit(ch):
            modifier = int(ch) - 1
            ch = yield
            s += ch
        return s, _sequence_key(code + ch, modifier)
    ch = yield
    s += ch
    if ch == "[":
        code += ch
        ch = yield
        s += ch
    command_start = len(s) - 1
    if _digit(ch):
        ch = yield
        s += ch
        if _digit(ch):
            ch = yield
            s += ch
            if _digit(ch):
                ch = yield
                s += ch
    if ch == ";":
        ch = yield
        s += ch
        if _digit(ch):
            s += yield
    command, modifier = _command(s[command_start:])
    return s, _sequence_key(code + command, modifier)


def _command(text: str) -> tuple[str, int]:
    """A CSI sequence's command (``"24;5~"``) as its code (``"24~"``) and
    modifier (``4``)."""
    if (match := _TILDE_CODE.fullmatch(text)) is not None:
        if match[4]:
            return match[4], 0
        return match[1] + match[3], int(match[2] or 1) - 1
    if (match := _LETTER_CODE.fullmatch(text)) is not None:
        return match[4], int(match[3] or 1) - 1
    return text, 0


def decode(text: str) -> list[UserInput]:
    """The key presses in ``text`` read at once, with no input after it: a
    trailing ESC is the escape key, an unfinished sequence gives none."""
    decoder = KeyDecoder()
    events = decoder.feed(text)
    if decoder.escape_pending:
        events += decoder.timeout()
    return events
