"""What lets the suite run in random order across pytest-xdist workers.

- Each test file starts from the process state the last one found: environment, working
  directory, ``sys.path``, signal handlers, the root logger and the default socket timeout are
  put back after every file, and a file that changed one fails, naming it (CLAUDE.md).
- A module marked ``in_order`` (ports of describe blocks whose tests share state in file order,
  as vitest runs them) keeps its order under pytest-randomly and runs on one worker.
- The tests that use a database container (``_mysql``, ``_mssql``, ``_clickhouse``, ``_libsql``)
  run on one worker per database, so a runner starts each container once, not once per worker.

The last two are this plugin's scheduler, not ``xdist_group`` marks: xdist 3.8 groups by
rewriting ``item._nodeid``, which pytest 9.2 no longer reads (pytest-dev/pytest-xdist#1407), so
the marks are dropped without a word. The scheduler works from test ids and file text alone.
"""

from __future__ import annotations

import functools
import logging
import os
import re
import signal
import socket
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

IN_ORDER = "in_order"

CONTAINERS = ("mysql", "mssql", "clickhouse", "libsql")
"""Databases the tests run in Docker, one container per process that asks."""

# A test id names its database as a word of its own (``[mysql]``, ``[pyfect.sql.mssql.layer]``);
# a file that starts one uses its fixture module (``_mysql``) or fixture (``mysql_server``).
_NAMES = {name: re.compile(rf"(?<![A-Za-z0-9]){name}(?![A-Za-z])") for name in CONTAINERS}
_STARTS = {name: re.compile(rf"\b_{name}\b|\b{name}_server\b") for name in CONTAINERS}
_MARKED_IN_ORDER = re.compile(rf"\bmark\.{IN_ORDER}\b")
_SIGNALS = tuple(
    name
    for name in ("SIGINT", "SIGTERM", "SIGHUP", "SIGUSR1", "SIGUSR2", "SIGCHLD", "SIGWINCH")
    if hasattr(signal, name)
)


def scope_of(nodeid: str, file_text: str) -> str:
    """The unit of work ``nodeid`` is scheduled in: tests that share a scope run on one worker,
    in collection order. An ``in_order`` file is one scope; a test that can start a database
    container shares that database's scope (the one its id names, else every one its file
    uses); any other test is a scope of its own."""
    file, _, test = nodeid.partition("::")
    if _MARKED_IN_ORDER.search(file_text):
        return f"in-order:{file}"
    used = [name for name in CONTAINERS if _NAMES[name].search(test)] or [
        name for name in CONTAINERS if _STARTS[name].search(file_text)
    ]
    return "container:" + "+".join(used) if used else nodeid


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{IN_ORDER}: the module's tests share state in file order (ports of describe blocks);"
        " they keep that order and run on one xdist worker",
    )
    config.pluginmanager.register(_KeepOrder(), "pyfect-keep-order")


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_make_scheduler(config: pytest.Config, log: Any) -> object | None:
    if config.getoption("dist") not in ("load", "loadgroup"):
        return None
    from xdist.scheduler import LoadScopeScheduling  # pyright: ignore[reportMissingTypeStubs]

    root = config.rootpath

    @functools.cache
    def text(file: str) -> str:
        return (root / file).read_text(encoding="utf-8")

    class _Scheduling(LoadScopeScheduling):
        def _split_scope(self, nodeid: str) -> str:
            return scope_of(nodeid, text(nodeid.partition("::")[0]))

    return _Scheduling(config, log)


@dataclass(eq=False)  # a plugin: pluggy hashes it
class _KeepOrder:
    """Puts an ``in_order`` module's tests back in file order, in the places pytest-randomly
    shuffled them to."""

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> Iterator[None]:
        original = {id(item): index for index, item in enumerate(items)}
        yield
        by_module: dict[Path, list[int]] = {}
        for position, item in enumerate(items):
            if item.get_closest_marker(IN_ORDER) is not None:
                by_module.setdefault(item.path, []).append(position)
        for positions in by_module.values():
            ordered = sorted((items[p] for p in positions), key=lambda item: original[id(item)])
            for position, item in zip(positions, ordered, strict=True):
                items[position] = item


@dataclass(frozen=True)
class _Part:
    name: str
    read: Callable[[], Any]
    restore: Callable[[Any], None]

    def describe(self, before: Any, after: Any) -> str:
        if isinstance(before, dict) and isinstance(after, dict):
            was = cast("dict[object, object]", before)
            now = cast("dict[object, object]", after)
            keys = sorted(
                str(key) for key in was.keys() | now.keys() if was.get(key) != now.get(key)
            )
            return f"{self.name} ({', '.join(keys)})"
        return self.name


_PYTEST_OWN = "PYTEST_CURRENT_TEST"  # pytest sets it for every phase of every test


def _environ() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key != _PYTEST_OWN}


def _restore_environ(saved: dict[str, str]) -> None:
    for key in _environ().keys() - saved.keys():
        del os.environ[key]
    os.environ.update(saved)


def _signal_handlers() -> dict[str, Any]:
    return {name: signal.getsignal(getattr(signal, name)) for name in _SIGNALS}


def _restore_signals(saved: dict[str, Any]) -> None:
    for name, handler in saved.items():
        if handler is not None:
            signal.signal(getattr(signal, name), handler)


def _root_logger() -> tuple[int, list[logging.Handler], list[Any]]:
    root = logging.getLogger()
    return root.level, list(root.handlers), list(root.filters)


def _restore_root_logger(saved: tuple[int, list[logging.Handler], list[Any]]) -> None:
    root = logging.getLogger()
    level, handlers, filters = saved
    root.setLevel(level)
    root.handlers[:] = handlers
    root.filters[:] = filters


def _restore_path(saved: list[str]) -> None:
    sys.path[:] = saved


PARTS = (
    _Part("os.environ", _environ, _restore_environ),
    _Part("the working directory", os.getcwd, os.chdir),
    _Part("sys.path", lambda: list(sys.path), _restore_path),
    _Part("signal handlers", _signal_handlers, _restore_signals),
    _Part("the root logger", _root_logger, _restore_root_logger),
    _Part("socket.getdefaulttimeout()", socket.getdefaulttimeout, socket.setdefaulttimeout),
)


@pytest.fixture(autouse=True, scope="module")
def process_state_is_put_back() -> Iterator[None]:
    """The state every test file starts from, put back after it; a file that left a change
    fails here (CLAUDE.md, "Tests run in parallel")."""
    saved = [(part, part.read()) for part in PARTS]
    yield
    changed: list[str] = []
    for part, before in saved:
        after = part.read()
        if after != before:
            changed.append(part.describe(before, after))
            part.restore(before)
    if changed:
        pytest.fail(f"this file left {', '.join(changed)} changed; it is put back now")
