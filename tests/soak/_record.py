"""The soak's JSONL records: one ``Start``, a ``Sample`` every interval, one ``End``.

The sampler writes them and the analyser reads them back through ``parse``, which
checks every field once, so the rest of the analyser works on typed values.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, cast


@dataclass(frozen=True)
class Latency:
    """One workload's operations completed during one interval."""

    count: int
    errors: int
    p50: float | None
    """Seconds; ``None`` when nothing completed."""
    p99: float | None
    first_error: str | None = None
    """The first unexpected failure of the interval, described."""


@dataclass(frozen=True)
class Start:
    python: str
    gil: bool
    duration: float
    interval: float
    warmup: float
    kind: str = "start"


@dataclass(frozen=True)
class Sample:
    t: float
    """Seconds since the start."""
    rss_bytes: int
    gc_objects: int
    """Every object the garbage collector tracks."""
    objects: dict[str, int]
    """Live objects by type (``module.qualname``), for types with at least
    ``MIN_TYPE_COUNT`` instances."""
    fibers_live: int
    """Fibers started and not yet ended (the ``FiberRuntimeMetrics`` hooks)."""
    fiber_objects: int
    """``Fiber`` instances still in memory, ended or not."""
    fds: int
    threads: int
    cpu_seconds: float
    latency: dict[str, Latency]
    stalled: list[str] = field(default_factory=list[str])
    """Workloads that completed nothing for longer than the stall limit."""
    kind: str = "sample"


@dataclass(frozen=True)
class End:
    t: float
    shutdown_seconds: float | None
    """How long the workloads took to stop once interrupted; ``None`` if they
    did not stop within the limit."""
    fibers_live: int
    """Fibers still running once everything stopped (should be 0)."""
    error: str | None = None
    """A failure that ended the run early."""
    kind: str = "end"


type Record = Start | Sample | End


def dumps(record: Record) -> str:
    return json.dumps(asdict(record), separators=(",", ":"))


class RecordError(ValueError):
    pass


def _num(raw: dict[str, Any], key: str) -> float:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RecordError(f"{key!r} is not a number: {value!r}")
    return float(value)


def _int(raw: dict[str, Any], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RecordError(f"{key!r} is not an integer: {value!r}")
    return value


def _opt_num(raw: dict[str, Any], key: str) -> float | None:
    return None if raw.get(key) is None else _num(raw, key)


def _dict(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise RecordError(f"{key!r} is not an object: {value!r}")
    return cast(dict[str, Any], value)


def _latency(raw: dict[str, Any]) -> Latency:
    return Latency(
        count=_int(raw, "count"),
        errors=_int(raw, "errors"),
        p50=_opt_num(raw, "p50"),
        p99=_opt_num(raw, "p99"),
        first_error=None if raw.get("first_error") is None else str(raw["first_error"]),
    )


def parse(line: str) -> Record:
    loaded: object = json.loads(line)
    if not isinstance(loaded, dict):
        raise RecordError(f"not an object: {line[:80]!r}")
    raw = cast(dict[str, Any], loaded)
    match raw.get("kind"):
        case "start":
            return Start(
                python=str(raw.get("python")),
                gil=bool(raw.get("gil")),
                duration=_num(raw, "duration"),
                interval=_num(raw, "interval"),
                warmup=_num(raw, "warmup"),
            )
        case "sample":
            objects = _dict(raw, "objects")
            stalled: object = raw.get("stalled", [])
            if not isinstance(stalled, list):
                raise RecordError(f"'stalled' is not a list: {stalled!r}")
            return Sample(
                t=_num(raw, "t"),
                rss_bytes=_int(raw, "rss_bytes"),
                gc_objects=_int(raw, "gc_objects"),
                objects={name: _int(objects, name) for name in objects},
                fibers_live=_int(raw, "fibers_live"),
                fiber_objects=_int(raw, "fiber_objects"),
                fds=_int(raw, "fds"),
                threads=_int(raw, "threads"),
                cpu_seconds=_num(raw, "cpu_seconds"),
                latency={
                    name: _latency(cast(dict[str, Any], value))
                    for name, value in _dict(raw, "latency").items()
                },
                stalled=[str(name) for name in cast(list[object], stalled)],
            )
        case "end":
            error = raw.get("error")
            return End(
                t=_num(raw, "t"),
                shutdown_seconds=_opt_num(raw, "shutdown_seconds"),
                fibers_live=_int(raw, "fibers_live"),
                error=None if error is None else str(error),
            )
        case other:
            raise RecordError(f"unknown kind {other!r}")


def read(text: str) -> list[Record]:
    """Every record of a JSONL file. A last line cut short (a run still writing, or
    killed mid-write) is skipped."""
    lines = [line for line in text.splitlines() if line.strip()]
    records: list[Record] = []
    for index, line in enumerate(lines):
        try:
            records.append(parse(line))
        except json.JSONDecodeError:
            if index == len(lines) - 1:
                break
            raise
    return records
