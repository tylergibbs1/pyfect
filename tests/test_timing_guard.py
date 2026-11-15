"""Tests read the clock only through ``tests/_timing.py``.

A test that times work with the wall clock fails when the machine is busy:
``tests/test_persistent_collections.py`` compared ``perf_counter`` times of two sizes and
failed up to half its runs under pytest-xdist on a loaded machine, and fixed limits on
pure computation (``test_glob``, ``test_multipart_boundary``, ``test_channel_io``,
``test_find_my_way``) did the same on slow CI runners. ``_timing.assert_scales`` measures
growth in thread CPU time; ``_timing.wait_until`` waits for another thread as a hang
detector. Timing a test checks goes through the ``TestClock``.

``_TIMED_IO`` lists files that still read the clock themselves, with how many reads each
has: real servers, databases and subprocesses timed against their own timeouts. A file
leaves the list when its reads go; a count that grows, or a new file, fails here.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

TESTS = Path(__file__).resolve().parent

_CLOCKS = frozenset(
    f"{name}{suffix}"
    for name in ("perf_counter", "monotonic", "thread_time", "process_time")
    for suffix in ("", "_ns")
)

_TIMED_IO: dict[str, int] = {
    "_connection_release.py": 2,
    "cross_run/_hammer.py": 2,
    "cross_run/cases_fibers.py": 6,
    "cross_run/test_run_ownership.py": 2,
    "fuzz/_harness.py": 2,
    "fuzz/server_target.py": 2,
    "interleave/_harness.py": 5,
    "oracle/_clickhouse.py": 2,
    "oracle/_interrupt_on_server.py": 4,
    "oracle/_libsql.py": 2,
    "oracle/_live_http.py": 2,
    "oracle/_mssql.py": 2,
    "oracle/_mysql.py": 2,
    "oracle/_pg_owner.py": 2,
    "oracle/_postgres.py": 2,
    "oracle/_redis.py": 2,
    "oracle/test_child_process_spawner.py": 2,
    "oracle/test_clickhouse_driver.py": 2,
    "oracle/test_completions.py": 2,
    "oracle/test_libsql_driver.py": 4,
    "oracle/test_live_server_node_semantics.py": 17,
    "oracle/test_mssql_client.py": 10,
    "oracle/test_mysql_cancellation.py": 2,
    "oracle/test_mysql_interrupt_on_server.py": 8,
    "oracle/test_node_http_server.py": 4,
    "oracle/test_pg_client.py": 2,
    "oracle/test_pg_pool.py": 4,
    "oracle/test_pg_reaping.py": 2,
    "oracle/test_pg_sql_event_journal.py": 2,
    "oracle/test_redis_py.py": 4,
    "oracle/test_sql_event_log_server_encrypted_storage.py": 2,
    "soak/_health.py": 1,
    "soak/_sampler.py": 5,
    "soak/_soak.py": 6,
    "soak/_workload.py": 2,
    "test_asgi_server_startup.py": 2,
    "test_base_exceptions.py": 3,
    "test_blocking_pool.py": 4,
    "test_fibers.py": 2,
    "test_file_system_watch.py": 2,
    "test_gc_census.py": 2,
    "test_httpx_test_clock.py": 2,
    "test_live_server_request_parsing.py": 4,
    "test_live_server_slow_head.py": 2,
    "test_process.py": 2,
    "test_server_idle_connection_shutdown.py": 2,
    "test_test_clock.py": 6,
    "test_test_clock_thread_work.py": 2,
    "test_testing_harness.py": 4,
    "test_uvicorn_server.py": 14,
    "test_workers.py": 4,
}


def _clock_reads(source: str) -> int:
    reads = 0
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in _CLOCKS
            and isinstance(node.value, ast.Name)
            and node.value.id == "time"
        ):
            reads += 1
        elif isinstance(node, ast.ImportFrom) and node.module == "time":
            reads += sum(alias.name in _CLOCKS for alias in node.names)
    return reads


def _reads_by_file() -> Counter[str]:
    reads: Counter[str] = Counter()
    for path in sorted(TESTS.rglob("*.py")):
        name = path.relative_to(TESTS).as_posix()
        if name != "_timing.py":
            reads[name] = _clock_reads(path.read_text())
    return +reads


def test_tests_read_the_clock_through_the_timing_helpers() -> None:
    assert dict(_reads_by_file()) == _TIMED_IO, (
        "time work with _timing.assert_scales, wait for threads with _timing.wait_until, "
        "and check timing with the TestClock"
    )


def test_the_guard_sees_every_way_to_read_the_clock() -> None:
    source = (
        "import time\nfrom time import perf_counter, sleep\n"
        "a = time.monotonic()\nb = time.perf_counter_ns()\nc = perf_counter()\n"
        "d = time.thread_time()\ntime.sleep(1)\nclock.monotonic()\n"
    )
    # The import of perf_counter counts once, the call through it not again.
    assert _clock_reads(source) == 4
