"""Command lines: the single strings a shell or a Windows program turns back
into arguments, and argument lists from templates (Effect's
``CommandLine``). Unrelated to ``pyfect.cli``, which parses your own
program's arguments.

The rules depend on what reads the string, not on the platform building it,
so ``quote``, ``join`` and ``display`` take a ``format``:

- ``"posix"`` (the default): ``sh``, ``dash``, ``bash`` and ``zsh``; ``fish``
  reads the quoted output the same way.
- ``"powershell"``: PowerShell 7.3 or later.
- ``"windows"``: the Microsoft C runtime rules most Windows programs split
  their command line with (not ``cmd.exe``'s).

Arguments can be ``Redacted`` strings: ``quote`` and ``join`` include their
values, because their output is meant to run; ``display`` shows
``<redacted>``::

    command_line.join(["git", "commit", "-m", "fix: don't fail"])
    # Ok("git commit -m 'fix: don'\\\\''t fail'")
    command_line.template(t"git commit -m {msg} {files}")  # Python 3.14
    command_line.template(["git commit -m ", " ", ""], msg, files)

A template is its literal text parts and the values between them, as a
tagged template gives them (or a t-string on Python 3.14). The text is split
into words as a POSIX shell does (quotes and backslash escapes removed);
text that needs a shell (operators, expansions, globs, comments, a variable
assignment) fails with ``UnsupportedSyntax``; each value is one literal
argument, or part of the surrounding one; a list adds one argument per item
and must stand alone; an argument containing a ``Redacted`` value is
``Redacted`` as a whole. Error messages never include the input.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, cast

from pyfect._js import js_number
from pyfect.errors import TaggedError
from pyfect.redacted import Redacted
from pyfect.redacted import make as redact
from pyfect.redacted import value as reveal
from pyfect.result import Err, Ok, Result

__all__ = [
    "CommandLineError",
    "Format",
    "Reason",
    "TemplateExpression",
    "TemplateExpressionItem",
    "TemplateLike",
    "TemplateStrings",
    "Word",
    "display",
    "join",
    "quote",
    "template",
]

type Format = Literal["posix", "powershell", "windows"]
"""The syntax a command line is read with."""

type Word = str | Redacted[str]
"""One argument: a string, or a ``Redacted`` one kept out of logs."""

type TemplateExpressionItem = str | int | float | bool | Redacted[str]
"""One value of a template."""

type TemplateExpression = TemplateExpressionItem | Sequence[TemplateExpressionItem]
"""A value of a template: a list or tuple adds one argument per item."""

type TemplateStrings = list[str] | tuple[str, ...]
"""The text parts of a template, as a tagged template gets them (a ``str``
is not one, so ``make("ls", ...)`` cannot be read as a template)."""

type Reason = Literal[
    "NulCharacter", "InvalidArgument", "InvalidEscape", "UnterminatedQuote", "UnsupportedSyntax"
]


@dataclass(eq=False)
class CommandLineError(TaggedError):
    """A command line or a template could not be built; ``reason`` says why.

    - ``NulCharacter``: an argument to ``quote`` or ``join`` contains NUL.
    - ``InvalidArgument``: the format cannot carry an argument (a Windows
      program name with ``"``, or ``--%`` for PowerShell).
    - ``InvalidEscape``: template text ends with a backslash escaping nothing.
    - ``UnterminatedQuote``: a quote in a template is not closed.
    - ``UnsupportedSyntax``: template text needs a shell, or a list value
      is not a separate argument.
    """

    reason: Reason
    message: str

    def __str__(self) -> str:
        return self.message


class _Interpolation(Protocol):
    @property
    def value(self) -> object: ...


class TemplateLike(Protocol):
    """Python 3.14's ``string.templatelib.Template`` (a t-string)."""

    @property
    def strings(self) -> tuple[str, ...]: ...
    @property
    def interpolations(self) -> tuple[_Interpolation, ...]: ...


def quote(word: Word, *, format: Format = "posix") -> Result[str, CommandLineError]:
    """``word`` quoted so a program reading ``format`` sees exactly one
    argument (PowerShell never passes ``--%`` on, however quoted: ``join``
    refuses it).

    ``"posix"`` leaves words of letters, digits and ``_ @ + : , . / -`` as
    they are and single-quotes the rest, ``'`` and ``\\`` written outside the
    quotes; ``"powershell"`` always single-quotes, doubling ``'`` and the
    typographic single quotes; ``"windows"`` quotes words with a space, tab,
    line break or ``"`` by the C runtime's backslash rules. The result holds
    a ``Redacted`` argument's value: use ``display`` for logs."""
    text = _unwrap(word)
    if "\0" in text:
        return _fail_nul("The argument")
    return Ok(_quote_word(format, text, program=False))


def join(words: Sequence[Word], *, format: Format = "posix") -> Result[str, CommandLineError]:
    """A command line running ``words[0]`` with the rest as its arguments,
    each quoted as ``quote`` does and separated by spaces; empty for no
    words. ``"posix"`` also quotes a program name a shell reads as a
    reserved word (``if``, ``time``); ``"powershell"`` starts with the call
    operator ``&``; ``"windows"`` quotes the program name without backslash
    escapes, and refuses one containing ``"``. ``"powershell"`` refuses an
    argument ``--%``. The result holds ``Redacted`` values: use ``display``
    for logs."""
    texts: list[str] = []
    for i, word in enumerate(words):
        text = _unwrap(word)
        if "\0" in text:
            return _fail_nul(f"Argument {i}")
        texts.append(text)
    if not texts:
        return Ok("")
    if format == "powershell":
        if "--%" in texts[1:]:
            index = texts.index("--%", 1)
            return Err(
                CommandLineError(
                    "InvalidArgument",
                    f'Argument {index} is "--%", which PowerShell drops when it calls a program',
                )
            )
    elif format == "windows" and '"' in texts[0]:
        return Err(
            CommandLineError(
                "InvalidArgument", "A Windows program name cannot contain a double quote"
            )
        )
    return Ok(
        _join_words(
            format, [_quote_word(format, text, program=i == 0) for i, text in enumerate(texts)]
        )
    )


def display(words: Sequence[Word], *, format: Format = "posix") -> str:
    """``words`` for logs and error messages: quoted as ``join`` does, with
    ``Redacted`` arguments as ``<redacted>`` and control characters and
    Unicode line separators as escapes (``\\n``, ``\\u001b``). Never fails;
    the output is for reading, not running."""
    if not words:
        return ""
    # Escaping after quoting keeps the escapes inside the quotes.
    return _join_words(
        format,
        [
            "<redacted>"
            if isinstance(word, Redacted)
            else _escape_control_characters(_quote_word(format, word, program=i == 0))
            for i, word in enumerate(words)
        ],
    )


def template(
    strings: TemplateStrings | TemplateLike, /, *values: TemplateExpression
) -> Result[list[Word], CommandLineError]:
    """The argument list of a template: its text parts ``strings`` and the
    ``values`` between them (one fewer), or a t-string alone. See the module
    docstring for the rules. Neither text nor values are checked for NUL:
    ``join`` and the spawner reject it."""
    if isinstance(strings, (list, tuple)):
        texts = tuple(strings)
        items: tuple[object, ...] = values
    else:
        if values:
            raise TypeError("a t-string carries its own values")
        texts = strings.strings
        items = tuple(i.value for i in strings.interpolations)
    if len(texts) != len(items) + 1:
        raise TypeError(
            f"a template needs one more text part than values, got {len(texts)} and {len(items)}"
        )
    return _Parser(texts, tuple(map(_expression, items))).parse()


type _Value = TemplateExpressionItem | tuple[TemplateExpressionItem, ...]


def _expression(value: object) -> _Value:
    """A template value checked at the boundary (a t-string's are not typed)."""
    if isinstance(value, (list, tuple)):
        items = cast("tuple[object, ...]", tuple(value))  # pyright: ignore[reportUnknownArgumentType]
        return tuple(map(_item, items))
    return _item(value)


def _item(value: object) -> TemplateExpressionItem:
    kind = type(value).__name__
    if isinstance(value, Redacted):
        redacted = cast("Redacted[object]", value)
        if isinstance(reveal(redacted), str):
            return cast("Redacted[str]", redacted)
    elif isinstance(value, (str, int, float)):
        return value
    raise TypeError(f"a template value is a str, int, float, bool or Redacted str, got {kind}")


# --- quoting ----------------------------------------------------------------------


def _unwrap(item: TemplateExpressionItem) -> str:
    if isinstance(item, Redacted):
        return reveal(item)
    return _to_text(item)


def _to_text(item: str | int | float | bool) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, bool):
        return "true" if item else "false"
    return js_number(item)


def _to_word(item: TemplateExpressionItem) -> Word:
    return item if isinstance(item, Redacted) else _to_text(item)


def _fail_nul(subject: str) -> Err[CommandLineError]:
    return Err(CommandLineError("NulCharacter", f"{subject} contains a NUL character"))


# Words sh, bash, zsh or fish read as syntax in the program position; quoted,
# a reserved word is an ordinary command name.
_RESERVED_WORDS = frozenset(
    {
        "!",
        "{",
        "}",
        "and",
        "begin",
        "case",
        "coproc",
        "do",
        "done",
        "elif",
        "else",
        "end",
        "esac",
        "fi",
        "for",
        "foreach",
        "function",
        "if",
        "in",
        "nocorrect",
        "not",
        "or",
        "repeat",
        "select",
        "switch",
        "then",
        "time",
        "until",
        "while",
    }
)


def _quote_word(format: Format, text: str, *, program: bool) -> str:
    match format:
        case "posix":
            return f"'{text}'" if program and text in _RESERVED_WORDS else _quote_posix(text)
        case "powershell":
            return _quote_powershell(text)
        case "windows":
            if program and '"' not in text:
                return _quote_windows_program(text)
            return _quote_windows_argument(text)


def _join_words(format: Format, quoted: list[str]) -> str:
    line = " ".join(quoted)
    return f"& {line}" if format == "powershell" else line


_POSIX_SAFE = re.compile(r"[A-Za-z0-9_@+:,./-]+")
_POSIX_OUTSIDE = re.compile(r"['\\]")


def _quote_posix(text: str) -> str:
    # `'` and `\` go outside the quotes: fish reads `\'` and `\\` as escapes
    # inside single quotes.
    if _POSIX_SAFE.fullmatch(text):
        return text
    return "'" + _POSIX_OUTSIDE.sub(lambda m: f"'\\{m[0]}'", text) + "'"


_POWERSHELL_QUOTES = re.compile(r"['\u2018\u2019\u201a\u201b]")


def _quote_powershell(text: str) -> str:
    return "'" + _POWERSHELL_QUOTES.sub(lambda m: m[0] * 2, text) + "'"


_WINDOWS_NEEDS_QUOTES = re.compile(r'[ \t\n\v"]')


def _quote_windows_argument(text: str) -> str:
    # 2n backslashes before a quote mean n, 2n+1 mean n and a literal quote;
    # other backslashes are literal.
    if text and not _WINDOWS_NEEDS_QUOTES.search(text):
        return text
    out = ['"']
    backslashes = 0
    for char in text:
        if char == "\\":
            backslashes += 1
        elif char == '"':
            out.append("\\" * (backslashes * 2 + 1) + '"')
            backslashes = 0
        else:
            out.append("\\" * backslashes + char)
            backslashes = 0
    out.append("\\" * (backslashes * 2) + '"')
    return "".join(out)


def _quote_windows_program(text: str) -> str:
    # Program names group with quotes but have no backslash escapes.
    return text if text and not re.search(r"[ \t]", text) else f'"{text}"'


_CONTROL_CHARACTERS = re.compile(r"[\u0000-\u001f\u007f-\u009f\u2028\u2029]")
_CONTROL_ESCAPES = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _escape_control_characters(text: str) -> str:
    return _CONTROL_CHARACTERS.sub(
        lambda m: _CONTROL_ESCAPES.get(m[0], f"\\u{ord(m[0]):04x}"), text
    )


# --- templates --------------------------------------------------------------------

_OPERATORS = "|&;<>()"
_GLOBS = "*?["
_EXPANSION_START = re.compile(r"[A-Za-z_0-9{(@*#?$!'\"-]")
_QUOTED_EXPANSION_START = re.compile(r"[A-Za-z_0-9{(@*#?$!-]")
_ASSIGNMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?")
_DOUBLE_QUOTE_ESCAPES = '$`"\\\n'


def _is_blank(char: str | None) -> bool:
    return char in (" ", "\t", "\n")


def _unsupported_syntax(char: str, following: str | None, *, word_start: bool) -> str | None:  # noqa: PLR0911
    """Why an unquoted character needs a shell, if it does."""
    if char in _OPERATORS:
        return f'The operator "{char}" needs a shell'
    if char == "`":
        return "Command substitution needs a shell"
    if char == "$" and following is not None and _EXPANSION_START.fullmatch(following):
        return f'The expansion "${following}" needs a shell'
    if char in _GLOBS:
        return f'The glob character "{char}" needs a shell'
    if not word_start:
        return None
    if char == "#":
        return "A comment needs a shell"
    if char == "~":
        return "Tilde expansion needs a shell"
    if char == "=" and following is not None and not _is_blank(following):
        return 'A leading "=" is expanded by zsh'
    return None


class _Failed(Exception):
    def __init__(self, error: CommandLineError) -> None:
        self.error = error


class _Parser:
    """POSIX quote removal over the text parts, the values inserted between
    them."""

    __slots__ = (
        "brace_depth",
        "part",
        "plain",
        "quote",
        "quote_part",
        "texts",
        "values",
        "word",
        "words",
    )

    def __init__(self, texts: tuple[str, ...], values: tuple[_Value, ...]) -> None:
        self.texts = texts
        self.values = values
        self.words: list[Word] = []
        # The current word, empty until it starts; an opened quote adds "".
        self.word: list[Word] = []
        # The current word is unquoted literal text, so it can name a
        # variable assignment.
        self.plain = True
        self.brace_depth = 0
        self.quote: Literal["'", '"'] | None = None
        self.quote_part = 0
        self.part = 0

    def parse(self) -> Result[list[Word], CommandLineError]:
        try:
            self._parse()
        except _Failed as failed:
            return Err(failed.error)
        return Ok(self.words)

    def _error(self, reason: Reason, message: str, at: int | None = None) -> _Failed:
        part = self.part if at is None else at
        return _Failed(CommandLineError(reason, f"{message} in template part {part}"))

    def _parse(self) -> None:
        while self.part < len(self.texts):
            self._scan(self.texts[self.part])
            if self.part == len(self.values):
                break
            expression = self.values[self.part]
            if isinstance(expression, tuple):
                # A list stands alone: nothing may touch it on either side.
                rest = self.texts[self.part + 1]
                touching = self.part + 1 < len(self.values) if not rest else not _is_blank(rest[0])
                if self.word or touching:
                    raise self._error(
                        "UnsupportedSyntax", "An interpolated array must be a separate argument"
                    )
                self.words.extend(_to_word(item) for item in expression)
            else:
                self.word.append(_to_word(expression))
                self.plain = False
            self.part += 1
        if self.quote is not None:
            raise self._error("UnterminatedQuote", "The quote is not closed", self.quote_part)
        self._end_word()

    def _end_word(self) -> None:
        word = self.word
        if not word:
            return
        if len(word) == 1 and isinstance(word[0], Redacted):
            self.words.append(word[0])
        else:
            text = "".join(_unwrap(piece) for piece in word)
            redacted = any(isinstance(piece, Redacted) for piece in word)
            self.words.append(redact(text) if redacted else text)
        self.word = []
        self.plain = True
        self.brace_depth = 0

    def _scan(self, text: str) -> None:  # noqa: PLR0912
        i = 0
        while i < len(text):
            char = text[i]
            following = text[i + 1] if i + 1 < len(text) else None
            if self.quote == "'":
                if char == "'":
                    self.quote = None
                else:
                    self.word.append(char)
            elif self.quote == '"':
                if char == '"':
                    self.quote = None
                elif char == "\\" and following is not None and following in _DOUBLE_QUOTE_ESCAPES:
                    if following != "\n":
                        self.word.append(following)
                    i += 1
                elif char == "`":
                    raise self._error("UnsupportedSyntax", "Command substitution needs a shell")
                elif (
                    char == "$"
                    and following is not None
                    and _QUOTED_EXPANSION_START.fullmatch(following)
                ):
                    raise self._error(
                        "UnsupportedSyntax", f'The expansion "${following}" needs a shell'
                    )
                else:
                    self.word.append(char)
            elif _is_blank(char):
                self._end_word()
            elif char == "\\":
                if following is None:
                    raise self._error("InvalidEscape", "A trailing backslash escapes nothing")
                if following != "\n":
                    self.word.append(following)
                    self.plain = False
                i += 1
            elif char in ("'", '"'):
                self.quote = char
                self.quote_part = self.part
                self.word.append("")
                self.plain = False
            else:
                self._literal(char, following)
            i += 1

    def _literal(self, char: str, following: str | None) -> None:
        unsupported = _unsupported_syntax(char, following, word_start=not self.word)
        if unsupported is not None:
            raise self._error("UnsupportedSyntax", unsupported)
        if char == "{":
            self.brace_depth += 1
        elif char == "}":
            if self.brace_depth > 0:
                self.brace_depth -= 1
        elif self.brace_depth > 0 and (char == "," or (char == "." and following == ".")):
            raise self._error("UnsupportedSyntax", "Brace expansion needs a shell")
        elif (
            char == "="
            and not self.words
            and self.plain
            and _ASSIGNMENT_NAME.fullmatch("".join(_unwrap(piece) for piece in self.word))
        ):
            raise self._error("UnsupportedSyntax", "A variable assignment needs a shell")
        self.word.append(char)
