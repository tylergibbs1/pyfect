"""Judges a soak run from its records: after the warm-up, memory, object, fiber,
file descriptor and thread counts must stay flat, latency must not rise, no
workload may stall, and the run must end with every fiber stopped."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ._record import End, Record, Sample, Start
from ._trend import Point, Trend, floor, median, trend


@dataclass(frozen=True)
class Growth:
    """A series grows when its fitted floor rises by more than ``absolute`` and by
    more than ``relative`` of where it started, steadily (Kendall's tau at least
    ``tau``)."""

    absolute: float
    relative: float
    tau: float = 0.6

    def exceeded(self, found: Trend) -> bool:
        return (
            found.growth > self.absolute
            and found.relative > self.relative
            and found.tau >= self.tau
            and found.rising
        )


@dataclass(frozen=True)
class Rise:
    """Latency rises when its fitted median grows to ``factor`` times where it
    started, by at least ``absolute`` seconds, steadily."""

    factor: float
    absolute: float
    tau: float = 0.6

    def exceeded(self, found: Trend) -> bool:
        return (
            found.growth > self.absolute
            and found.growth > (self.factor - 1) * max(found.start, 0.0)
            and found.tau >= self.tau
            and found.rising
        )


MIB = 1024 * 1024


@dataclass(frozen=True)
class Limits:
    rss: Growth = Growth(absolute=32 * MIB, relative=0.10)
    gc_objects: Growth = Growth(absolute=20_000, relative=0.10)
    object_type: Growth = Growth(absolute=2_000, relative=0.25)
    fibers_live: Growth = Growth(absolute=50, relative=0.25)
    fiber_objects: Growth = Growth(absolute=100, relative=0.25)
    fds: Growth = Growth(absolute=16, relative=0.25)
    threads: Growth = Growth(absolute=4, relative=0.25)
    p50: Rise = Rise(factor=2.0, absolute=0.005)
    p99: Rise = Rise(factor=3.0, absolute=0.025)
    error_ratio: float = 0.005
    """Unexpected failures a workload may have, as a share of its operations."""
    shutdown_seconds: float = 60.0
    latency: bool = True
    """Judge latency. A run of a few minutes has no baseline long enough to tell a rise
    from load elsewhere on the machine; errors are judged either way."""


@dataclass(frozen=True)
class Finding:
    check: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class Report:
    findings: list[Finding]

    @property
    def ok(self) -> bool:
        return all(finding.ok for finding in self.findings)

    @property
    def failures(self) -> list[Finding]:
        return [finding for finding in self.findings if not finding.ok]

    def text(self) -> str:
        lines = [f"{'ok  ' if f.ok else 'FAIL'} {f.check}: {f.detail}" for f in self.findings]
        lines.append("PASS" if self.ok else f"FAIL ({len(self.failures)} checks)")
        return "\n".join(lines)


def _series(samples: Sequence[Sample], value: Callable[[Sample], float | None]) -> list[Point]:
    return [(s.t, v) for s in samples if (v := value(s)) is not None]


def _describe(found: Trend, unit: Callable[[float], str]) -> str:
    return f"{unit(found.start)} -> {unit(found.start + found.growth)} (tau {found.tau:+.2f})"


def _count(value: float) -> str:
    return f"{value:,.0f}"


def _mib(value: float) -> str:
    return f"{value / MIB:,.1f} MiB"


def _ms(value: float) -> str:
    return f"{value * 1000:,.1f} ms"


def _growth_check(
    name: str, points: list[Point], limit: Growth, unit: Callable[[float], str]
) -> Finding | None:
    found = trend(points, floor)
    if found is None:
        return None
    return Finding(name, not limit.exceeded(found), _describe(found, unit))


def _object_types(samples: Sequence[Sample], limit: Growth) -> list[Finding]:
    """One finding per type that grew, or one saying none did."""
    names = set[str]().union(*(s.objects for s in samples[-3:]))
    grown: list[Finding] = []
    for name in sorted(names):
        found = trend(_series(samples, lambda s, n=name: s.objects.get(n, 0)), floor)
        if found is not None and limit.exceeded(found):
            grown.append(Finding(f"objects {name}", False, _describe(found, _count)))
    if grown:
        return grown
    return [Finding("objects by type", True, f"{len(names)} types, none growing")]


def _percentile_of(workload: str, label: str) -> Callable[[Sample], float | None]:
    def pick(sample: Sample) -> float | None:
        found = sample.latency.get(workload)
        if found is None:
            return None
        return found.p50 if label == "p50" else found.p99

    return pick


def _latency(samples: Sequence[Sample], limits: Limits) -> list[Finding]:
    findings: list[Finding] = []
    workloads = sorted(set[str]().union(*(s.latency for s in samples)))
    for workload in workloads:
        ops = sum(s.latency[workload].count for s in samples if workload in s.latency)
        errors = sum(s.latency[workload].errors for s in samples if workload in s.latency)
        ratio = errors / ops if ops else 0.0
        findings.append(
            Finding(
                f"{workload} errors",
                ops > 0 and ratio <= limits.error_ratio,
                f"{errors:,} unexpected failures in {ops:,} operations",
            )
        )
        for label, rise in (("p50", limits.p50), ("p99", limits.p99)) if limits.latency else ():
            pick = _percentile_of(workload, label)
            found = trend(_series(samples, pick), median)
            if found is not None:
                name = f"{workload} {label}"
                findings.append(Finding(name, not rise.exceeded(found), _describe(found, _ms)))
    return findings


def _stalls(samples: Sequence[Sample]) -> Finding:
    stalled = [(s.t, name) for s in samples for name in s.stalled]
    if not stalled:
        return Finding("stalls", True, "every workload kept completing operations")
    first = ", ".join(f"{name} at {t:,.0f}s" for t, name in stalled[:5])
    return Finding("stalls", False, f"{len(stalled)} stalled samples: {first}")


def _end(end: End | None, limits: Limits) -> list[Finding]:
    if end is None:
        return [Finding("end", False, "the run did not finish (no end record)")]
    findings = [
        Finding("run", end.error is None, end.error or f"ran {end.t:,.0f}s"),
        Finding(
            "shutdown",
            end.shutdown_seconds is not None and end.shutdown_seconds <= limits.shutdown_seconds,
            "did not stop"
            if end.shutdown_seconds is None
            else f"stopped in {end.shutdown_seconds:.2f}s",
        ),
        Finding(
            "fibers after shutdown",
            end.fibers_live == 0,
            f"{end.fibers_live} still running",
        ),
    ]
    return findings


def analyse(
    records: Sequence[Record], limits: Limits | None = None, *, finished: bool = True
) -> Report:
    """``finished=False`` judges a run still going: no end record is expected."""
    limits = limits or Limits()
    start = next((r for r in records if isinstance(r, Start)), None)
    if start is None:
        return Report([Finding("start", False, "no start record")])
    samples = [r for r in records if isinstance(r, Sample)]
    steady = [s for s in samples if s.t >= start.warmup]
    findings: list[Finding] = [
        Finding(
            "samples",
            True,
            f"{len(samples)} samples, {len(steady)} after the {start.warmup:,.0f}s warm-up "
            f"({'GIL' if start.gil else 'free-threaded'} Python {start.python})",
        )
    ]
    checks: list[tuple[str, Callable[[Sample], float], Growth, Callable[[float], str]]] = [
        ("rss", lambda s: s.rss_bytes, limits.rss, _mib),
        ("gc objects", lambda s: s.gc_objects, limits.gc_objects, _count),
        ("live fibers", lambda s: s.fibers_live, limits.fibers_live, _count),
        ("fiber objects", lambda s: s.fiber_objects, limits.fiber_objects, _count),
        ("fds", lambda s: s.fds, limits.fds, _count),
        ("threads", lambda s: s.threads, limits.threads, _count),
    ]
    judged = False
    for name, value, limit, unit in checks:
        finding = _growth_check(name, _series(steady, value), limit, unit)
        if finding is not None:
            findings.append(finding)
            judged = True
    if not judged:
        findings.append(Finding("trends", False, "too few samples after the warm-up to judge"))
    else:
        findings.extend(_object_types(steady, limits.object_type))
        findings.extend(_latency(steady, limits))
    findings.append(_stalls(samples))
    if finished:
        end = next((r for r in records if isinstance(r, End)), None)
        findings.extend(_end(end, limits))
    return Report(findings)
