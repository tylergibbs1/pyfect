"""The counts docs/PARITY.md states, worked out from the rows and titles they count.

- §4's ``Counts after the merge: a N, b N, c done N, c kept N, c open N``, from each §4 row's
  class cell;
- §5's ``(N §4 rows, `<class>`)``, from the §4 rows whose class starts with ``<class>``;
- ``N titles NOT_PORTED, all open``, from the Effect checkout CI pins (``_effect_ref.py``): the
  titles no test ports that ``_effect_title_omissions.py`` files as ``NOT_PORTED``.

    uv run python tests/_parity_counts.py           # fail, naming each stale count
    uv run python tests/_parity_counts.py --write   # rewrite the counts from what they count

Without the Effect checkout the title count is left as it is and the run fails, saying how to
get one; the other counts are still checked or written. ``tests/test_parity_section4.py`` and
``tests/test_effect_titles.py`` fail on a stale count and say to run this.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import _effect_ref
from _effect_title_omissions import open_title_count
from _effect_titles import effect_files_in, unported_titles

PARITY = Path(__file__).resolve().parent.parent / "docs" / "PARITY.md"
WRITE = "uv run python tests/_parity_counts.py --write"
CLASSES = ("a", "b", "c done", "c kept", "c open")

_CELL = re.compile(r"(?<!\\)\|")
_CLASS_COUNTS = re.compile(
    r"Counts after the merge: a \d+, b \d+, c done \d+, c kept \d+, c open \d+"
)
_DECISION_COUNT = re.compile(r"\((\d+) §4 rows, `([^`]+)`\)")
_OPEN_TITLES = re.compile(r"(\d+) titles NOT_PORTED, all open")


class BadRow(ValueError):
    """A §4 row whose cells are not the header's."""


@dataclass(frozen=True)
class Row:
    line: int
    """Its line in docs/PARITY.md."""
    cells: tuple[str, ...]

    @property
    def feature(self) -> str:
        return self.cells[0]

    @property
    def kind(self) -> str:
        """The class cell: ``a``, ``b: <reason>``, ``c done``, ``c kept: <why>``, ..."""
        return self.cells[-1]


def _cells(line: str) -> tuple[str, ...]:
    return tuple(cell.strip() for cell in _CELL.split(line)[1:-1])


def section_four(text: str) -> list[Row]:
    """The rows of §4's table. Raises ``BadRow`` on a row with more or fewer cells than the
    header, naming its line: an unescaped ``|`` splits a cell even inside backticks."""
    start = text.index("## 4. Pythonic decisions")
    end = text.index("\n## 5.", start)
    first = text.count("\n", 0, start) + 1
    table = [
        (first + offset, line)
        for offset, line in enumerate(text[start:end].splitlines())
        if line.startswith("|")
    ]
    width = len(_cells(table[0][1]))
    rows = [Row(number, _cells(line)) for number, line in table[2:]]
    for row in rows:
        if len(row.cells) != width:
            raise BadRow(
                f"docs/PARITY.md:{row.line}: the §4 row {row.feature!r} has {len(row.cells)} "
                f"cells, not {width}. A `|` inside a cell, backticked or not, ends the cell: "
                "write it `\\|`."
            )
    return rows


def class_counts(rows: list[Row]) -> tuple[int, ...]:
    """How many rows each of ``CLASSES`` has."""
    found = Counter(row.kind.split(":")[0] for row in rows)
    return tuple(found[name] for name in CLASSES)


def _class_line(counts: tuple[int, ...]) -> str:
    return "Counts after the merge: " + ", ".join(
        f"{name} {count}" for name, count in zip(CLASSES, counts, strict=True)
    )


@dataclass(frozen=True)
class Rewrite:
    text: str
    stale: list[str]
    """One line per count that ``text`` changed: what it said and what it says now."""


def _replace(
    text: str, pattern: re.Pattern[str], new: Callable[[re.Match[str]], str]
) -> tuple[str, list[str]]:
    stale: list[str] = []

    def one(match: re.Match[str]) -> str:
        replacement = new(match)
        if replacement != match[0]:
            stale.append(f"{match[0]!r} should be {replacement!r}")
        return replacement

    return pattern.sub(one, text), stale


def rewrite(text: str, open_titles: int | None) -> Rewrite:
    """``text`` with its counts worked out again (the title count only when ``open_titles``
    is given). Raises ``ValueError`` when a count it keeps is missing."""
    rows = section_four(text)
    if len(_CLASS_COUNTS.findall(text)) != 1:
        raise ValueError(f"docs/PARITY.md has no one {_CLASS_COUNTS.pattern!r}")
    text, stale = _replace(text, _CLASS_COUNTS, lambda _: _class_line(class_counts(rows)))

    def decision(match: re.Match[str]) -> str:
        count = sum(row.kind.startswith(match[2]) for row in rows)
        return f"({count} §4 rows, `{match[2]}`)"

    text, more = _replace(text, _DECISION_COUNT, decision)
    stale += more
    if open_titles is not None:
        if len(_OPEN_TITLES.findall(text)) != 1:
            raise ValueError(f"docs/PARITY.md has no one {_OPEN_TITLES.pattern!r}")
        text, more = _replace(
            text, _OPEN_TITLES, lambda _: f"{open_titles} titles NOT_PORTED, all open"
        )
        stale += more
    return Rewrite(text, stale)


def _open_titles() -> int | str:
    """The open title count, or why it can't be counted here."""
    try:
        checkout = _effect_ref.checkout()
    except (_effect_ref.NoCheckout, _effect_ref.WrongCommit) as missing:
        return f"the title count is not checked: {missing}"
    return open_title_count(unported_titles(effect_files_in(checkout)))


def main(argv: list[str]) -> int:
    write = argv == ["--write"]
    if argv not in ([], ["--write"]):
        print("usage: tests/_parity_counts.py [--write]", file=sys.stderr)
        return 2
    titles = _open_titles()
    done = rewrite(PARITY.read_text(), titles if isinstance(titles, int) else None)
    if write:
        PARITY.write_text(done.text)
    for line in done.stale:
        print(f"{'rewrote' if write else 'stale'}: {line}")
    if isinstance(titles, str):
        print(titles, file=sys.stderr)
        return 1
    if done.stale and not write:
        print(f"run `{WRITE}`", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
