"""Any order of test paths on the command line finds every conftest fixture.

pytest 9.1 lost the fixtures of ``tests/oracle/conftest.py`` for the second oracle file of
``pytest tests/oracle/test_a.py tests/test_b.py tests/oracle/test_c.py`` ("fixture
'pg_server' not found"); 9.2.0 fixed it (pytest-dev/pytest#14635). This lays out the same
shape as this suite: a top-level directory without ``__init__.py`` and a package below it
whose conftest re-exports fixtures, one of them parametrized, from a private module.
"""

import itertools

import pytest

_FILES = ("tests/sub/test_a.py", "tests/test_top.py", "tests/sub/test_b.py")


@pytest.mark.parametrize("order", list(itertools.permutations(_FILES)), ids=str)
def test_interleaved_paths_keep_the_package_conftest_fixtures(
    pytester: pytest.Pytester, order: tuple[str, ...]
) -> None:
    pytester.mkdir("tests")
    pytester.mkpydir("tests/sub")
    pytester.makepyfile(
        **{
            "tests/sub/_servers": """
                import pytest

                @pytest.fixture
                def server():
                    return "up"

                @pytest.fixture(params=["sqlite", "pg"])
                def backend(request):
                    return request.param
            """,
            "tests/sub/conftest": "from ._servers import backend, server",
            "tests/sub/test_a": "def test_a(server, backend): assert server == 'up'",
            "tests/sub/test_b": "def test_b(server, backend): assert server == 'up'",
            "tests/test_top": "def test_top(): pass",
        }
    )

    result = pytester.runpytest_subprocess("-p", "no:cacheprovider", *order)

    result.assert_outcomes(passed=5)
