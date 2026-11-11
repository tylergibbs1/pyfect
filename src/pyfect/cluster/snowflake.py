"""Snowflake ids (Effect's ``Snowflake``): 64-bit ids that sort by the
millisecond they were made, ``timestamp - EPOCH_MILLIS`` in the top bits,
then a 10-bit machine id and a 12-bit sequence."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Never, NewType

from pyfect import layer as layer_
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.brand import Brand
from pyfect.clock import Clock, ClockService, now_millis_unsafe
from pyfect.cluster.machine_id import MachineId
from pyfect.context import Tag
from pyfect.date_time._epoch import from_epoch_millis
from pyfect.effect import sync

Snowflake = NewType("Snowflake", int)

SnowflakeFromBigInt = S.BigInt.pipe(S.from_brand(Brand[int, Snowflake].nominal()))
"""Snowflakes as integers."""

SnowflakeFromString = S.BigIntFromString.pipe(S.from_brand(Brand[int, Snowflake].nominal()))
"""Snowflakes encoded as their decimal digits."""

EPOCH_MILLIS = 1_735_689_600_000
"""2025-01-01T00:00:00Z, the zero of a snowflake's timestamp."""


@dataclass(frozen=True, slots=True)
class Parts:
    timestamp: int
    machine_id: MachineId
    sequence: int


def make(*, machine_id: MachineId, sequence: int, timestamp: int) -> Snowflake:
    """The snowflake made at ``timestamp`` (Unix milliseconds); the machine
    id is taken mod 1024 and the sequence mod 4096."""
    return Snowflake((timestamp - EPOCH_MILLIS) << 22 | (machine_id % 1024) << 12 | sequence % 4096)


def timestamp(snowflake: Snowflake) -> int:
    """The Unix milliseconds ``snowflake`` was made at."""
    return (snowflake >> 22) + EPOCH_MILLIS


def date_time(snowflake: Snowflake) -> datetime:
    return from_epoch_millis(timestamp(snowflake))


def machine_id(snowflake: Snowflake) -> MachineId:
    return MachineId((snowflake >> 12) % 1024)


def sequence(snowflake: Snowflake) -> int:
    return snowflake % 4096


def to_parts(snowflake: Snowflake) -> Parts:
    return Parts(timestamp(snowflake), machine_id(snowflake), sequence(snowflake))


class SnowflakeGenerator:
    """Makes unique snowflakes for one machine. Within a millisecond the
    sequence counts up; after 4096 the generator borrows the next
    millisecond, and a clock behind it (gone back, or behind the borrowed
    milliseconds) keeps counting on the last one."""

    __slots__ = ("_clock", "_machine_id", "_sequence", "_sequence_at")

    def __init__(self, clock: ClockService, machine_id: MachineId) -> None:
        self._clock = clock
        self._machine_id = machine_id
        self._sequence = 0
        self._sequence_at = self._now()

    def _now(self) -> int:
        return now_millis_unsafe(self._clock)

    def set_machine_id(self, machine_id: MachineId) -> Effect[None]:
        def run() -> None:
            self._machine_id = machine_id

        return sync(run)

    def next_unsafe(self) -> Snowflake:
        now = self._now()
        if now > self._sequence_at:
            self._sequence = 0
            self._sequence_at = now
        elif self._sequence >= 4096:
            # Exhausted, and the clock has not passed this millisecond: borrow the next one.
            self._sequence_at += 1
            self._sequence = 0
        sequence = self._sequence
        self._sequence += 1
        return make(machine_id=self._machine_id, sequence=sequence, timestamp=self._sequence_at)


def make_generator() -> Effect[SnowflakeGenerator]:
    """A generator on the current ``Clock``, with a random machine id
    until ``set_machine_id``."""
    return Clock().map(lambda clock: SnowflakeGenerator(clock, MachineId(random.randrange(1024))))


class Generator(Tag[SnowflakeGenerator], key="effect/cluster/Snowflake/Generator"):
    """The snowflake generator of this runner."""


layer_generator: layer_.Layer[Generator, Never] = layer_.effect(Generator, make_generator())
"""A snowflake ``Generator`` from ``make_generator``: the current ``Clock`` and a random
machine id until ``set_machine_id``."""

__all__ = [
    "EPOCH_MILLIS",
    "Generator",
    "Parts",
    "Snowflake",
    "SnowflakeFromBigInt",
    "SnowflakeFromString",
    "SnowflakeGenerator",
    "date_time",
    "layer_generator",
    "machine_id",
    "make",
    "make_generator",
    "sequence",
    "timestamp",
    "to_parts",
]
