"""Inventories of tests allowed to break a rule, each entry with its reason.

A line is ``key value  # reason``; a line starting with ``#`` is a comment. The reason
names what the entry depends on that the rule cannot cover (a database's own lock
timeout, a child process's clock), so an entry is only ever added with a reason to
weigh, and removed once that reason goes.
"""

from __future__ import annotations

from dataclasses import dataclass

_SEPARATOR = "  # "
_MIN_WORDS = 3
"""A reason names a dependency and why the rule cannot cover it; "slow" or "flaky
test" names neither."""
_DISCLAIMERS = ("no real-time", "no real time", "none", "not needed", "no dependency")
"""Openings of a reason that says there is no reason: such an entry is a test to fix."""


@dataclass(frozen=True, slots=True)
class Entry:
    value: str
    reason: str


class InventoryError(ValueError):
    pass


def parse(text: str) -> dict[str, Entry]:
    """The entries of an inventory, by key; raises ``InventoryError`` naming every bad line."""
    entries: dict[str, Entry] = {}
    problems: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        body, _, reason = line.partition(_SEPARATOR)
        key, _, value = body.strip().partition(" ")
        reason = reason.strip()
        if len(reason.split()) < _MIN_WORDS:
            problems.append(
                f"line {number}: {key} has no reason: end the line with '  # ' and what it "
                "depends on in real time that the TestClock cannot drive"
            )
        elif reason.lower().startswith(_DISCLAIMERS):
            problems.append(
                f"line {number}: {key} says it needs no real time: fix it and remove its line"
            )
        elif key in entries:
            problems.append(f"line {number}: {key} is listed twice")
        else:
            entries[key] = Entry(value.strip(), reason)
    if problems:
        raise InventoryError("\n".join(problems))
    return entries
