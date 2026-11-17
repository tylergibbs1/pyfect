"""The lines of an MCP peer's NDJSON over stdio, framed as Effect frames them
(``McpClient.ts`` ``stdio``, and ``RpcSerialization.ndjson`` under
``McpServer.layerStdio``): a line ends at ``\\n``, without a ``\\r`` before it.
Text after the last ``\\n`` when the input ends is no message and is dropped,
where ``split_lines`` would give it as a last line."""

from __future__ import annotations

from collections.abc import Sequence

from pyfect._core import Effect
from pyfect.channel import LineTooLongError
from pyfect.effect import fail, succeed
from pyfect.stream import Stream


class _Pending:
    """The text of a line not ended yet, in pieces joined once it ends."""

    __slots__ = ("length", "pieces")

    def __init__(self) -> None:
        self.pieces: list[str] = []
        self.length = 0


def ndjson_lines[E, R](
    text: Stream[str, E, R], max_length: int
) -> Stream[str, E | LineTooLongError, R]:
    """The lines of ``text``; a line, ended or not, longer than ``max_length``
    characters fails with ``LineTooLongError``."""

    def split(
        pending: _Pending, chunk: str
    ) -> Effect[tuple[_Pending, Sequence[str]], LineTooLongError]:
        if "\n" not in chunk:
            pending.pieces.append(chunk)
            pending.length += len(chunk)
            if pending.length > max_length:
                return fail(LineTooLongError(max_length))
            return succeed((pending, ()))
        *ended, rest = "".join([*pending.pieces, chunk]).split("\n")
        lines = [line.removesuffix("\r") for line in ended]
        if len(rest) > max_length or any(len(line) > max_length for line in lines):
            return fail(LineTooLongError(max_length))
        pending.pieces = [rest] if rest else []
        pending.length = len(rest)
        return succeed((pending, lines))

    return text.map_accum_effect(_Pending, split)
