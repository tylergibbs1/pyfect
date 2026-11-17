"""Every place in ``src/`` that starts threads is one of a known few, each
bounded. A thread started per call lets whoever drives the calls start any
number of them: system DNS lookups each took a thread of their own until
getaddrinfo returned, so lookups of slow names abandoned by a timeout left
one thread each (``tests/test_dns_lookup_pool.py``). Work that would take a
thread per call goes to a bounded pool instead: ``fx.blocking``'s, or the
four lookup threads (``pyfect._lookup.on_lookup_thread``).

This walks the sources for calls that start threads and fails on one that
is not listed below with the reason it is bounded."""

import ast

import _source

_SOURCE = _source.SRC
_STARTS_THREADS = frozenset(
    {
        "Thread",
        "Timer",
        "start_new_thread",
        "ThreadPoolExecutor",
        "ProcessPoolExecutor",
        "to_thread",
        "LoopThread",
    }
)

_SANCTIONED: dict[tuple[str, str], str] = {
    ("_blocking_pool.py", "Thread"): "the bounded pools: fx.blocking's and the four lookup threads",
    ("_loop_thread.py", "Thread"): "a LoopThread's one thread",
    ("scheduler.py", "Thread"): "the one background scheduler thread",
    ("_blocking_watchdog.py", "Thread"): "one watchdog, started by PYFECT_WARN_BLOCKING",
    ("_stack.py", "ThreadPoolExecutor"): (
        "joined before it returns, nested at most MAX_FRESH_STACKS deep"
    ),
    ("file_system/_native_watch.py", "Thread"): "one per watch the program starts",
    ("terminal/_resize.py", "Thread"): "one per process, while any listener is subscribed",
    ("process/_child.py", "Thread"): "one per child process, watching for its exit",
    ("process/_pipes.py", "Thread"): "one per pipe of a child process",
    ("workers/_thread.py", "Thread"): "one per thread worker the program starts",
    ("workers/_process.py", "Thread"): "one reader per worker process",
    ("workers/_frames.py", "Thread"): "one writer per worker's socket",
    ("http/_asgi_listener.py", "LoopThread"): "one per process",
    ("socket/_loop.py", "LoopThread"): "one per process",
    ("sql/_loop.py", "LoopThread"): "one per process",
    ("http/httpx_client.py", "LoopThread"): "one per HTTP client",
    ("persistence/redis_py.py", "LoopThread"): "one per Redis client",
    ("sql/sqlite/_worker.py", "ThreadPoolExecutor"): "one per connection, bounded by the pool",
    ("sql/mssql/_worker.py", "ThreadPoolExecutor"): "one per connection, bounded by the pool",
    ("sql/libsql/_local.py", "ThreadPoolExecutor"): "one per connection, bounded by the pool",
}


def _called_name(call: ast.Call) -> str | None:
    match call.func:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None


def _runs_on_the_default_executor(call: ast.Call) -> bool:
    """``loop.run_in_executor(None, ...)``: asyncio's default executor, a
    pool this guard cannot see the bound of."""
    return (
        _called_name(call) == "run_in_executor"
        and bool(call.args)
        and isinstance(call.args[0], ast.Constant)
        and call.args[0].value is None
    )


def _thread_sites() -> set[tuple[str, str]]:
    sites: set[tuple[str, str]] = set()
    for path in _source.files(_SOURCE):
        if not _source.mentions(path, *_STARTS_THREADS, "run_in_executor"):
            continue
        relative = path.relative_to(_SOURCE).as_posix()
        for node in _source.walk(path):
            if not isinstance(node, ast.Call):
                continue
            if _runs_on_the_default_executor(node):
                sites.add((relative, "run_in_executor(None)"))
            elif (name := _called_name(node)) in _STARTS_THREADS:
                sites.add((relative, name))
    return sites


def test_threads_start_only_in_sanctioned_places() -> None:
    unsanctioned = sorted(_thread_sites() - _SANCTIONED.keys())
    assert unsanctioned == [], (
        "start threads through a bounded pool (fx.blocking, pyfect._lookup.on_lookup_thread), "
        "or add the site to _SANCTIONED with why it is bounded"
    )


def test_every_sanctioned_place_still_starts_threads() -> None:
    assert sorted(_SANCTIONED.keys() - _thread_sites()) == []
