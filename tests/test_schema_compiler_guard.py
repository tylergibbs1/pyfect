"""No test can leave a schema compiler installed for the tests after it.

A test that imported ``pyfect.schema.jit_compiler.install`` (a walk over every
module did) used to compile every schema parsed in the rest of the run.
``conftest.py`` fails such a test and resets the registry.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_CONFTEST = Path(__file__).with_name("conftest.py")


def test_a_test_that_leaves_the_jit_installed_fails_and_the_next_parses_by_interpreting(
    pytester: pytest.Pytester,
) -> None:
    pytester.makeconftest(_CONFTEST.read_text())
    pytester.syspathinsert(_CONFTEST.parent)
    pytester.makepyfile(
        """
        import importlib
        import sys

        from pyfect.schema.compiler import _registry


        def test_installs():
            name = "pyfect.schema.jit_compiler.install"
            if name in sys.modules:
                importlib.reload(sys.modules[name])
            else:
                importlib.import_module(name)


        def test_after():
            assert not _registry.active()
        """
    )
    result = pytester.runpytest_inprocess("-p", "no:randomly")
    result.assert_outcomes(passed=2, errors=1)
    result.stdout.fnmatch_lines(["*this test left a schema compiler installed*"])


def test_collecting_tests_that_install_the_jit_stops_the_run(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(_CONFTEST.read_text())
    pytester.syspathinsert(_CONFTEST.parent)
    pytester.makepyfile(
        """
        import importlib
        import sys

        name = "pyfect.schema.jit_compiler.install"
        if name in sys.modules:
            importlib.reload(sys.modules[name])
        else:
            importlib.import_module(name)


        def test_nothing():
            pass
        """
    )
    try:
        result = pytester.runpytest_inprocess("-p", "no:randomly")
        assert result.ret == pytest.ExitCode.USAGE_ERROR
        result.stderr.fnmatch_lines(["*collecting the tests left a schema compiler installed*"])
    finally:
        from pyfect.schema.compiler import _registry

        _registry.reset()
