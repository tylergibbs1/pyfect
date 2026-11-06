"""Finds where a token split between chunks ends."""

from __future__ import annotations

from typing import Final

TAB: Final = 9
LF: Final = 10
CR: Final = 13
SPACE: Final = 32
BANG: Final = 33
DQUOTE: Final = 34
SQUOTE: Final = 39
DASH: Final = 45
LT: Final = 60
GT: Final = 62
QUESTION: Final = 63
LBRACKET: Final = 91
RBRACKET: Final = 93

S_START: Final = 0
S_TEXT: Final = 1
S_LT: Final = 2  # after "<"
S_BANG: Final = 3  # after "<!"
S_KEYWORD: Final = 4  # matching the rest of "<!--", "<![CDATA[" or "<!DOCTYPE"
S_COMMENT: Final = 5
S_CDATA: Final = 6
S_PI: Final = 7
S_TAG: Final = 8
S_DOCTYPE: Final = 9  # a DOCTYPE before its internal subset
S_SUBSET: Final = 10
S_SUBSET_LT: Final = 11
S_SUBSET_BANG: Final = 12
S_SUBSET_BANG_DASH: Final = 13
S_SUBSET_COMMENT: Final = 14
S_SUBSET_PI: Final = 15
S_DECLARATION: Final = 16  # a markup declaration in the internal subset
S_AFTER_SUBSET: Final = 17


class Scanner:
    """Scans a token one character at a time, so that the scan can resume in
    the next chunk. A token "ends" where it is complete or where it is known to
    be malformed; the parser then reads the complete token from a single string."""

    __slots__ = ("aux", "keyword", "state")

    def __init__(self) -> None:
        self.state = S_START
        # A count of matched keyword characters or trailing "-", "]" or "?"
        # characters, or an open quote
        self.aux = 0
        self.keyword = ""

    def reset(self, state: int) -> None:
        self.state = state
        self.aux = 0

    def scan(self, s: str, i: int) -> int:  # noqa: PLR0911, PLR0912, PLR0915
        """An index of ``s`` at which the token has ended, or -1."""
        n = len(s)
        while i < n:
            c = ord(s[i])
            state = self.state
            if state == S_START:
                self.state = S_LT if c == LT else S_TEXT
                if c != LT:
                    continue
            elif state == S_TEXT:
                return s.find("<", i)
            elif state == S_LT:
                if c == BANG:
                    self.state = S_BANG
                elif c == QUESTION:
                    self.reset(S_PI)
                else:
                    self.reset(S_TAG)
                    continue
            elif state == S_BANG:
                if c == DASH:
                    self.keyword = "--"
                elif c == LBRACKET:
                    self.keyword = "[CDATA["
                elif c == 68:
                    self.keyword = "DOCTYPE"
                else:
                    return i
                self.state = S_KEYWORD
                self.aux = 1
            elif state == S_KEYWORD:
                if c != ord(self.keyword[self.aux]):
                    return i
                self.aux += 1
                if self.aux == len(self.keyword):
                    self.reset(
                        S_COMMENT
                        if self.keyword == "--"
                        else S_DOCTYPE
                        if self.keyword == "DOCTYPE"
                        else S_CDATA
                    )
            elif state in (S_COMMENT, S_SUBSET_COMMENT):
                if c == DASH:
                    self.aux += 1
                elif c == GT and self.aux >= 2:
                    if state == S_COMMENT:
                        return i + 1
                    self.reset(S_SUBSET)
                else:
                    self.aux = 0
            elif state == S_CDATA:
                if c == RBRACKET:
                    self.aux += 1
                elif c == GT and self.aux >= 2:
                    return i + 1
                else:
                    self.aux = 0
            elif state in (S_PI, S_SUBSET_PI):
                if c == GT and self.aux == 1:
                    if state == S_PI:
                        return i + 1
                    self.reset(S_SUBSET)
                else:
                    self.aux = 1 if c == QUESTION else 0
            elif state == S_TAG:
                # Attribute values cannot contain "<"
                if c == LT:
                    return i
                if self.aux == 0:
                    if c == GT:
                        return i + 1
                    if c in (DQUOTE, SQUOTE):
                        self.aux = c
                elif c == self.aux:
                    self.aux = 0
            elif state in (S_DOCTYPE, S_DECLARATION):
                if self.aux == 0:
                    if c == LT:
                        return i
                    if c == GT:
                        if state == S_DOCTYPE:
                            return i + 1
                        self.reset(S_SUBSET)
                    elif c == LBRACKET and state == S_DOCTYPE:
                        self.reset(S_SUBSET)
                    elif c in (DQUOTE, SQUOTE):
                        self.aux = c
                elif c == self.aux:
                    self.aux = 0
            elif state == S_SUBSET:
                if c == RBRACKET:
                    self.state = S_AFTER_SUBSET
                elif c == LT:
                    self.state = S_SUBSET_LT
                elif c in (DQUOTE, SQUOTE, GT):
                    return i
            elif state == S_SUBSET_LT:
                if c == BANG:
                    self.state = S_SUBSET_BANG
                elif c == QUESTION:
                    self.reset(S_SUBSET_PI)
                else:
                    return i
            elif state == S_SUBSET_BANG:
                if c == DASH:
                    self.state = S_SUBSET_BANG_DASH
                else:
                    self.reset(S_DECLARATION)
                    continue
            elif state == S_SUBSET_BANG_DASH:
                if c != DASH:
                    return i
                self.reset(S_SUBSET_COMMENT)
            elif state == S_AFTER_SUBSET:
                if c == GT:
                    return i + 1
                if c not in (SPACE, LF, TAB, CR):
                    return i
            i += 1
        return -1
