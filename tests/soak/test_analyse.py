"""The soak analyser passes flat runs, whatever their noise, and fails leaking ones."""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import replace

import pytest

from ._analyse import MIB, Limits, analyse
from ._record import End, Latency, Record, Sample, Start, dumps, read
from ._trend import kendall_tau, percentile, theil_sen

HOUR = 3600.0
INTERVAL = 30.0
WARMUP = 600.0


def _sample(t: float, rng: random.Random) -> Sample:
    """A healthy process at ``t``: flat levels with noise, a GC sawtooth on memory and
    objects, and latency with occasional spikes."""
    saw = (t % 300) / 300  # a GC cycle every five minutes
    spike = 10.0 if rng.random() < 0.05 else 1.0
    return Sample(
        t=t,
        rss_bytes=int(200 * MIB + 40 * MIB * saw + rng.gauss(0, 4 * MIB)),
        gc_objects=int(300_000 + 60_000 * saw + rng.gauss(0, 5_000)),
        objects={
            "builtins.dict": int(80_000 + 20_000 * saw + rng.gauss(0, 2_000)),
            "pyfect._fiber.Fiber": int(300 + rng.gauss(0, 60)),
        },
        fibers_live=max(0, int(120 + rng.gauss(0, 40))),
        fiber_objects=max(0, int(300 + rng.gauss(0, 60))),
        fds=int(40 + rng.randint(-5, 5)),
        threads=8 + rng.randint(0, 2),
        cpu_seconds=t * 0.2,
        latency={
            "http": Latency(
                count=1000,
                errors=rng.randint(0, 1),
                p50=0.002 * spike * rng.uniform(0.8, 1.5),
                p99=0.02 * spike * rng.uniform(0.7, 2.0),
            )
        },
    )


Change = Callable[[Sample], Sample]


def _run(
    hours: float = 2.0, change: Change = lambda s: s, *, seed: int = 1, end: End | None = None
) -> list[Record]:
    rng = random.Random(seed)
    duration = hours * HOUR
    records: list[Record] = [
        Start(python="3.14", gil=True, duration=duration, interval=INTERVAL, warmup=WARMUP)
    ]
    steps = int(duration / INTERVAL)
    records.extend(change(_sample(i * INTERVAL, rng)) for i in range(1, steps + 1))
    records.append(end or End(t=duration, shutdown_seconds=1.5, fibers_live=0))
    return records


def _failed(records: list[Record]) -> set[str]:
    return {finding.check for finding in analyse(records).failures}


@pytest.mark.parametrize("seed", range(8))
def test_a_flat_noisy_run_passes(seed: int) -> None:
    report = analyse(_run(seed=seed))
    assert report.ok, report.text()


def test_growth_during_the_warm_up_is_ignored() -> None:
    def warming(s: Sample) -> Sample:
        filled = min(s.t, WARMUP) / WARMUP
        return replace(s, rss_bytes=s.rss_bytes + int(300 * MIB * filled))

    assert analyse(_run(change=warming)).ok


def test_a_slow_memory_leak_under_the_sawtooth_fails() -> None:
    def leaking(s: Sample) -> Sample:
        return replace(s, rss_bytes=s.rss_bytes + int(30 * MIB * s.t / HOUR))

    assert "rss" in _failed(_run(change=leaking))


def test_a_leaking_object_type_fails_and_is_named() -> None:
    def leaking(s: Sample) -> Sample:
        objects = {**s.objects, "pyfect.scope.Scope": int(50 + 4_000 * s.t / HOUR)}
        return replace(s, objects=objects)

    assert "objects pyfect.scope.Scope" in _failed(_run(change=leaking))


def test_fibers_left_parked_fail() -> None:
    def leaking(s: Sample) -> Sample:
        stuck = int(s.t // 60)  # one more parked fiber a minute
        return replace(s, fibers_live=s.fibers_live + stuck, fiber_objects=s.fiber_objects + stuck)

    assert {"live fibers", "fiber objects"} <= _failed(_run(change=leaking))


def test_leaked_file_descriptors_and_threads_fail() -> None:
    def leaking(s: Sample) -> Sample:
        return replace(s, fds=s.fds + int(s.t // 120), threads=s.threads + int(s.t // 900))

    assert {"fds", "threads"} <= _failed(_run(change=leaking))


def test_rising_latency_fails() -> None:
    def slowing(s: Sample) -> Sample:
        http = s.latency["http"]
        assert http.p50 is not None and http.p99 is not None
        factor = 1 + 4 * s.t / (2 * HOUR)
        slower = replace(http, p50=http.p50 * factor, p99=http.p99 * factor)
        return replace(s, latency={"http": slower})

    assert {"http p50", "http p99"} <= _failed(_run(change=slowing))


def test_latency_can_be_left_unjudged() -> None:
    def slowing(s: Sample) -> Sample:
        http = s.latency["http"]
        assert http.p50 is not None
        return replace(s, latency={"http": replace(http, p50=http.p50 * (1 + s.t / 600))})

    report = analyse(_run(change=slowing), Limits(latency=False))
    assert report.ok, report.text()


def test_a_burst_of_slow_samples_is_not_a_rise() -> None:
    def burst(s: Sample) -> Sample:
        if not 3000 <= s.t < 3600:
            return s
        http = s.latency["http"]
        assert http.p50 is not None and http.p99 is not None
        return replace(s, latency={"http": replace(http, p50=http.p50 * 20, p99=http.p99 * 20)})

    assert analyse(_run(change=burst)).ok


def test_unexpected_errors_fail() -> None:
    def failing(s: Sample) -> Sample:
        return replace(s, latency={"http": replace(s.latency["http"], errors=50)})

    assert "http errors" in _failed(_run(change=failing))


def test_a_stall_fails() -> None:
    def stalling(s: Sample) -> Sample:
        return replace(s, stalled=["queue"]) if 4000 < s.t < 4100 else s

    assert "stalls" in _failed(_run(change=stalling))


@pytest.mark.parametrize(
    ("end", "check"),
    [
        (End(t=7200, shutdown_seconds=None, fibers_live=0), "shutdown"),
        (End(t=7200, shutdown_seconds=1.0, fibers_live=3), "fibers after shutdown"),
        (End(t=7200, shutdown_seconds=1.0, fibers_live=0, error="Die(boom)"), "run"),
    ],
)
def test_a_bad_ending_fails(end: End, check: str) -> None:
    assert check in _failed(_run(end=end))


def test_a_run_without_an_end_fails_unless_still_running() -> None:
    records = _run()[:-1]
    assert "end" in _failed(records)
    assert analyse(records, finished=False).ok


def test_too_short_a_run_cannot_pass() -> None:
    assert "trends" in _failed(_run(hours=0.25))


def test_records_round_trip_and_a_cut_last_line_is_skipped() -> None:
    records = _run(hours=0.5)
    text = "\n".join(map(dumps, records))
    assert read(text) == records
    assert read(text[:-5]) == records[:-1]


def test_the_statistics() -> None:
    line = [(float(t), 3.0 * t + 1) for t in range(10)]
    assert theil_sen(line) == pytest.approx(3.0)
    assert kendall_tau(line) == 1.0
    assert kendall_tau([(t, -y) for t, y in line]) == -1.0
    outlier = [*line[:5], (5.0, 1e9), *line[6:]]
    assert theil_sen(outlier) == pytest.approx(3.0)
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.5) == 3.0
    assert math.isclose(percentile([0.0, 10.0], 0.1), 1.0)
