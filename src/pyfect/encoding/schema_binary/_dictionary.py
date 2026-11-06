"""A connection dictionary: string tables that outlive one frame. The writer
and the reader build the same tables from the same frames, so a reference
means the same string on both ends. Leaves sharing a schema node share a
table.

A leaf starts out only watching: it writes plain strings and remembers them
until one comes back, and only then writes references. A leaf whose strings
never repeat gives up, so it never costs a byte more than no dictionary.
"""

from __future__ import annotations

from dataclasses import dataclass, field

WATCHING = 0
REFERENCING = 1
GAVE_UP = 2

WATCH_LIMIT = 64
"""How many distinct strings a leaf watches before giving up."""
MAX_ENTRIES = 512
"""How many strings one leaf keeps once it is referencing."""


@dataclass(slots=True, eq=False)
class DictSlot:
    values: list[str] = field(default_factory=list[str])
    refs: dict[str, int] = field(default_factory=dict[str, int])
    state: int = WATCHING
    stamp: int = -1
    """The frame that last touched this slot: one mark per frame."""

    def watch(self, value: str) -> None:
        if value in self.refs:
            self.state = REFERENCING
            return
        self.refs[value] = len(self.values)
        self.values.append(value)
        if len(self.values) >= WATCH_LIMIT:
            self.state = GAVE_UP

    def add(self, value: str) -> None:
        if len(self.values) < MAX_ENTRIES:
            self.refs[value] = len(self.values)
            self.values.append(value)


type DictRead = dict[int, DictSlot]


def dict_slot(slots: DictRead, index: int) -> DictSlot:
    slot = slots.get(index)
    if slot is None:
        slot = slots[index] = DictSlot()
    return slot


@dataclass(slots=True, eq=False)
class DictMark:
    slot: DictSlot
    length: int
    state: int


@dataclass(slots=True, eq=False)
class DictWrite:
    """A frame that fails is never sent, so its additions come back out or
    the reader's tables would drift from the writer's."""

    slots: DictRead = field(default_factory=dict[int, DictSlot])
    marks: list[DictMark] = field(default_factory=list[DictMark])
    frame: int = 0

    def mark(self, slot: DictSlot) -> None:
        if slot.stamp != self.frame:
            slot.stamp = self.frame
            self.marks.append(DictMark(slot, len(slot.values), slot.state))

    def commit(self) -> None:
        self.marks.clear()
        self.frame += 1

    def rollback(self) -> None:
        for mark in reversed(self.marks):
            for value in mark.slot.values[mark.length :]:
                del mark.slot.refs[value]
            del mark.slot.values[mark.length :]
            mark.slot.state = mark.state
        self.marks.clear()
        self.frame += 1
