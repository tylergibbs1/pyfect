"""tests/_parallel.py: in-order files and database tests keep to one xdist worker, in random
order runs too, and a file that leaves process state changed fails."""

from pathlib import Path

import _parallel
import pytest


@pytest.fixture(autouse=True)
def _plugin_importable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONPATH", str(Path(_parallel.__file__).parent))


_SEQUENCE = """
import pytest

pytestmark = pytest.mark.in_order
seen = []

{tests}
"""


def _sequence(count: int) -> str:
    tests = "\n".join(
        f"def test_{i:02d}():\n    assert seen == list(range({i}))\n    seen.append({i})\n"
        for i in range(count)
    )
    return _SEQUENCE.format(tests=tests)


def _independent(count: int) -> str:
    return "\n".join(f"def test_{i:02d}():\n    pass\n" for i in range(count))


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_an_in_order_file_runs_in_order_on_one_worker_in_a_random_parallel_run(
    pytester: pytest.Pytester, seed: int
):
    pytester.makepyfile(test_sequence=_sequence(20), test_other=_independent(20))
    result = pytester.runpytest_subprocess(
        "-p", "_parallel", "-p", "randomly", f"--randomly-seed={seed}", "-n", "3"
    )
    result.assert_outcomes(passed=40)


def test_the_scope_of_a_test() -> None:
    marked = "pytestmark = pytest.mark.in_order\n"
    assert _parallel.scope_of("t/test_a.py::test_x", marked) == "in-order:t/test_a.py"
    assert _parallel.scope_of("t/test_a.py::test_x[mysql]", "") == "container:mysql"
    assert (
        _parallel.scope_of("t/test_a.py::test_x[sqlite]", "from . import _mysql, _mssql\n")
        == "container:mysql+mssql"
    )
    assert _parallel.scope_of("t/test_a.py::test_x[mssql]", "from . import _mysql, _mssql\n") == (
        "container:mssql"
    )
    assert _parallel.scope_of("t/test_a.py::test_x[pyfect.sql.mssql.layer]", "") == (
        "container:mssql"
    )
    # A database only mentioned (a docstring, another dialect's name in prose) is not used.
    assert _parallel.scope_of("t/test_a.py::test_x", '"""Unlike mysql."""\n') == (
        "t/test_a.py::test_x"
    )


def test_a_file_that_leaves_the_environment_changed_fails(pytester: pytest.Pytester):
    pytester.makepyfile(
        test_leak="""
        import os

        def test_sets():
            os.environ["PYFECT_LEFT_BEHIND"] = "1"
        """,
        test_after="""
        import os

        def test_reads():
            assert "PYFECT_LEFT_BEHIND" not in os.environ
        """,
    )
    result = pytester.runpytest_subprocess("-p", "_parallel", "-p", "no:randomly")
    result.assert_outcomes(passed=2, errors=1)
    result.stdout.fnmatch_lines(["*this file left os.environ (PYFECT_LEFT_BEHIND) changed*"])


def test_a_file_that_leaves_a_signal_handler_installed_fails_naming_the_signal(
    pytester: pytest.Pytester,
):
    pytester.makepyfile(
        test_handler="""
        import signal

        def test_installs():
            signal.signal(signal.SIGUSR1, lambda *_: None)
        """
    )
    result = pytester.runpytest_subprocess("-p", "_parallel", "-p", "no:randomly")
    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*this file left signal handlers (SIGUSR1) changed*"])
