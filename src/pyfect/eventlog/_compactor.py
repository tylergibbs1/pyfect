"""Compactors as the registry holds them (Effect's ``Registry.compactors``),
here so the remote compaction engine can use them without the log."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from pyfect._core import Effect
from pyfect.eventlog.event_journal import Entry

type CompactWrite = Callable[[Entry, Entry | None], Effect[None]]
"""A compactor's output: an entry and, optionally, the input entry it
replaces (its anchor during remote replay; without one a matching id
keeps its position and a new id takes the group's start)."""


class CompactFn(Protocol):
    """A compactor: the entries of its events and ``write`` for what it
    keeps. ``remote`` is true during a remote compaction, which only drops
    entries."""

    def __call__(
        self, entries: Sequence[Entry], write: CompactWrite, /, *, remote: bool = False
    ) -> Effect[None]: ...


@dataclass(frozen=True, slots=True)
class RegisteredCompactor:
    """A compactor of ``events``; ``remote`` when it also runs over a
    remote's history to build snapshots."""

    events: frozenset[str]
    effect: CompactFn
    remote: bool = False
