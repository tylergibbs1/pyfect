"""Shared fixtures."""

import gc
import os
import re
from collections.abc import Iterator
from pathlib import Path

import _effect_ref
import pytest

from pyfect.schema.compiler import _registry

pytest_plugins = [
    "pytester",
    "_timeout",
    "_asyncio_reports",
    "_loop_registrations",
    "_unclosed_sockets",
    "_shards",
    "_skips",
    "_failures_named_at_once",
    "_git_config_guard",
    "_metric_registry",
    "_parallel",
    "_stalls",
    "_hypothesis_tables",
    "_leaked_threads",
    "_leaked_fibers",
    "_leaked_interpreters",
]

# pytest imports readline before this file loads, and GNU readline (Linux) exports COLUMNS and
# LINES into the C environment behind os.environ's back; children would inherit an 80-column
# terminal (``ps aux`` cuts its lines there). tests/test_session_environment.py pins this.
for _name in ("COLUMNS", "LINES"):
    if _name not in os.environ:
        os.unsetenv(_name)

_COMPILER_LEFT = (
    "a schema compiler installed (pyfect.schema.compiler: set, install, enable, or an "
    "import of pyfect.schema.jit_compiler.install), so every later test would parse through it; "
    "reset it with _registry.reset(), as the fresh_registry fixture in "
    "tests/oracle/_schema_compiler.py does, and walk modules with tests/_pyfect_modules.py"
)


def pytest_collection_finish(session: pytest.Session) -> None:
    """Keep imported modules out of the collector's work: with them, a full run holds over five
    million objects and one collection pauses the running test for up to 2.5 s."""
    if _registry.active():
        raise pytest.UsageError(f"collecting the tests left {_COMPILER_LEFT}")
    gc.collect()
    gc.freeze()


@pytest.fixture(autouse=True)
def no_schema_compiler_left_installed() -> Iterator[None]:
    """Each Effect test file runs in its own module graph; here one process runs them all, so
    a test that installs a compiler must remove it."""
    yield
    if _registry.active():
        _registry.reset()
        pytest.fail(f"this test left {_COMPILER_LEFT}")


@pytest.fixture(scope="session")
def effect_checkout() -> Path:
    """Effect's repository at the commit CI pins (``_effect_ref.py``): skips without a checkout
    and fails, naming both commits, on one at another commit."""
    try:
        return _effect_ref.checkout()
    except _effect_ref.NoCheckout as missing:
        pytest.skip(str(missing))
    except _effect_ref.WrongCommit as wrong:
        pytest.fail(str(wrong), pytrace=False)


@pytest.fixture(scope="session")
def ai_durable_crashes(tmp_path_factory: pytest.TempPathFactory) -> list[Path]:
    """One 100-turn durable agent run on SQLite, its database copied at every activity
    boundary (``_ai_durable_agent.crash_states``), made once per test process."""
    from _ai_durable_agent import crash_states

    import pyfect as fx

    return fx.run_blocking(crash_states(tmp_path_factory.mktemp("ai-durable-crashes")))


_ADDRESS = re.compile(r" at 0x[0-9a-fA-F]+")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """A test id holding an object's address differs between processes, so CI's shards and its
    completeness check would see different tests. Name parameters explicitly."""
    unstable = [item.nodeid for item in items if _ADDRESS.search(item.nodeid)]
    if unstable:
        raise pytest.UsageError(
            f"{len(unstable)} test ids hold an object address, e.g. {unstable[0][:300]}"
        )


@pytest.fixture
def pytester(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    """Pytester whose inner runs keep their files' order: pytest-randomly loads in every
    session from its entry point, and the inner tests here are written as sequences."""
    monkeypatch.setenv("PYTEST_ADDOPTS", "-p no:randomly")
    return pytester
