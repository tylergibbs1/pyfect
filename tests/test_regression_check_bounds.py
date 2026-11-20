"""(pyfect) ``scripts/check_regression_guards.py`` bounds every guarded test it runs.

An injected bug once held memory quadratic in its input (json-patch's copies): the guard's
test reached 16 GB in seconds, before the hang alarm's 60 s, and the nightly runner lost
contact with GitHub. A bug that spins inside one C call never lets the alarm run at all.
So each test runs in a process of its own, killed past a hard deadline or once it holds too
much memory; either counts as caught, as a hang does.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_regression_guards.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_regression_guards", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    path = sys.path[:]  # the script puts the repository first on it
    sys.modules[spec.name] = module  # its dataclass looks its module up there
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = path
    return module


_SCRIPT_MODULE = _module()


_TESTS = """
import signal


def test_passes():
    pass


def test_fails():
    assert 1 == 2


def test_spins_where_no_alarm_reaches():
    signal.signal(signal.SIGALRM, signal.SIG_IGN)
    while True:
        pass


def test_holds_ever_more_memory():
    held = []
    while True:
        held.append(b"x" * (64 << 20))
"""


def _run(tmp_path: Path, name: str, **bounds: float) -> tuple[str, str]:
    (tmp_path / "test_bounded.py").write_text(_TESTS)
    found = _SCRIPT_MODULE.run_guarded(
        f"test_bounded.py::{name}", cwd=tmp_path, src=tmp_path, **bounds
    )
    return found.verdict, found.why


def test_a_test_that_passes_against_its_bug_is_missed(tmp_path: Path) -> None:
    assert _run(tmp_path, "test_passes")[0] == "MISSED"


def test_a_test_that_fails_against_its_bug_is_caught(tmp_path: Path) -> None:
    assert _run(tmp_path, "test_fails")[0] == "caught"


def test_a_test_past_its_deadline_is_killed_and_caught(tmp_path: Path) -> None:
    verdict, why = _run(tmp_path, "test_spins_where_no_alarm_reaches", deadline=5)
    assert (verdict, why) == ("caught", "killed: still running after 5s")


def test_a_test_past_its_memory_is_killed_and_caught(tmp_path: Path) -> None:
    verdict, why = _run(tmp_path, "test_holds_ever_more_memory", memory=1 << 30, deadline=60)
    assert verdict == "caught", why
    assert why.startswith("killed: held "), why
    assert why.endswith(", over 1 GB"), why
