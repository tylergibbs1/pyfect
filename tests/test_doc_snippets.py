"""The guides' Python code runs, and only comes from checked files.

Every Python block in `website/content/docs` is an `<include>` of a file under
`website/snippets`, which pyright checks and these tests run (the site is built
from `website/` alone, so guides can't include files outside it):
a snippet asserts its own results, and `test_*.py` snippets are pytest files.

Snippets under `postgres/` and `mysql/` read `DATABASE_URL`: each runs on a fresh database
of the throwaway server the pg or MySQL tests use (`tests/oracle/_postgres.py`,
`tests/oracle/_mysql.py`), and skips without one.
The site build never runs snippets, so it needs no server.

A snippet that prints has its output next to it (`x.py` -> `x.out`), which guides show
in "Output" tabs. The file must equal what running the snippet prints; regenerate with

    UPDATE_SNIPPET_OUTPUT=1 uv run pytest tests/test_doc_snippets.py
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SNIPPETS = ROOT / "website" / "snippets"
GUIDES = ROOT / "website" / "content" / "docs"

INCLUDE = re.compile(r"<include[^>]*>\s*([^<]+?)\s*</include>")
PYTHON_FENCE = re.compile(r"^\s*(```|~~~)\s*(py|python|python3|pycon)\b", re.MULTILINE)


def snippet_files() -> list[Path]:
    return sorted(SNIPPETS.rglob("*.py"))


def output_files() -> list[Path]:
    return sorted(SNIPPETS.rglob("*.out"))


def guide_files() -> list[Path]:
    return sorted(GUIDES.rglob("*.mdx"))


def included_files(guide: Path) -> list[Path]:
    """The files a guide includes, resolved as Fumadocs does: relative to the
    guide, with any `#region` suffix removed."""
    targets = INCLUDE.findall(guide.read_text())
    return [(guide.parent / target.split("#")[0]).resolve() for target in targets]


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    # -P: don't put the snippet's directory on sys.path, as `python file.py` would.
    return subprocess.run(
        [sys.executable, "-P", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=ROOT,
        env=None if env is None else os.environ | env,
    )


POSTGRES = SNIPPETS / "postgres"
MYSQL = SNIPPETS / "mysql"


def mysql_env(path: Path) -> dict[str, str]:
    """`DATABASE_URL` of a new, empty database for a MySQL snippet."""
    from oracle._mysql import query_now, server

    mysql = server()  # skips without Docker
    database = "snippet_" + "_".join(path.relative_to(MYSQL).with_suffix("").parts)
    query_now(f"DROP DATABASE IF EXISTS `{database}`", root=True)
    query_now(f"CREATE DATABASE `{database}`", root=True)
    return {"DATABASE_URL": mysql.uri(root=True).rpartition("/")[0] + f"/{database}"}


def snippet_env(path: Path) -> dict[str, str] | None:
    """`DATABASE_URL` of a new, empty database for a PostgreSQL or MySQL
    snippet."""
    if path.is_relative_to(MYSQL):
        return mysql_env(path)
    if not path.is_relative_to(POSTGRES):
        return None
    from oracle._postgres import query_now, server

    pg = server()  # skips without a local PostgreSQL
    database = "snippet_" + "_".join(path.relative_to(POSTGRES).with_suffix("").parts)
    query_now(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
    query_now(f'CREATE DATABASE "{database}"')
    return {"DATABASE_URL": pg.uri.rpartition("/")[0] + f"/{database}"}


def name(path: Path) -> str:
    return str(path.relative_to(SNIPPETS))


SCRIPTS = [p for p in snippet_files() if not p.name.startswith("test_")]
TESTS = [p for p in snippet_files() if p.name.startswith("test_")]


@pytest.mark.parametrize("path", SCRIPTS, ids=name)
def test_snippet_runs(path: Path):
    done = run(str(path), env=snippet_env(path))
    assert done.returncode == 0, done.stderr
    expected = path.with_suffix(".out")
    if os.environ.get("UPDATE_SNIPPET_OUTPUT") and done.stdout:
        expected.write_text(done.stdout)
    if expected.exists():
        assert done.stdout == expected.read_text(), (
            f"{name(expected)} is stale: rerun with UPDATE_SNIPPET_OUTPUT=1"
        )
    else:
        assert not done.stdout, (
            f"{name(path)} prints; write {name(expected)} with UPDATE_SNIPPET_OUTPUT=1"
        )


@pytest.mark.parametrize("path", snippet_files(), ids=name)
def test_snippet_names_do_not_shadow_the_standard_library(path: Path):
    """Readers run `python file.py`, which puts the file's directory first on sys.path:
    a snippet named `queue.py` would hide the stdlib module and break `import pyfect`.
    `run` uses -P, so test_snippet_runs can't see this."""
    assert path.stem not in sys.stdlib_module_names, (
        f"{name(path)} shadows the standard-library module {path.stem!r}: rename it"
    )


@pytest.mark.parametrize("path", output_files(), ids=name)
def test_outputs_belong_to_snippets(path: Path):
    assert path.with_suffix(".py").is_file(), f"{name(path)} has no snippet"


@pytest.mark.parametrize("path", TESTS, ids=name)
def test_snippet_tests_pass(path: Path):
    done = run("-m", "pytest", "-q", "-p", "no:cacheprovider", str(path), env=snippet_env(path))
    assert done.returncode == 0, done.stdout + done.stderr


def test_there_are_guides_and_snippets():
    assert guide_files() and SCRIPTS and TESTS


@pytest.mark.parametrize("guide", guide_files(), ids=lambda p: p.name)
def test_guides_have_no_inline_python(guide: Path):
    """Python in a guide must be an `<include>` of a checked file."""
    assert not PYTHON_FENCE.search(guide.read_text()), (
        f"{guide.name} has an inline Python block: move it to website/snippets and include it"
    )


@pytest.mark.parametrize("guide", guide_files(), ids=lambda p: p.name)
def test_guides_include_only_checked_files(guide: Path):
    for target in included_files(guide):
        assert target.is_file(), f"{guide.name} includes a missing file: {target}"
        assert target.is_relative_to(SNIPPETS.resolve()), (
            f"{guide.name} includes {target}, outside website/snippets"
        )


def test_every_snippet_is_used_by_a_guide():
    used = {path for guide in guide_files() for path in included_files(guide)}
    unused = [name(p) for p in [*snippet_files(), *output_files()] if p.resolve() not in used]
    assert not unused, f"snippets no guide includes: {unused}"


DIAGRAMS = ROOT / "website" / "diagrams"
DIAGRAM = re.compile(r'<Diagram\s+name="([^"]+)"')


def test_diagrams_exist_and_are_used():
    """Guides draw diagrams from `website/diagrams/<name>.mmd` (rendered by pele at build)."""
    used = {name for guide in guide_files() for name in DIAGRAM.findall(guide.read_text())}
    files = {path.stem for path in DIAGRAMS.glob("*.mmd")}
    assert used <= files, f"missing diagram files: {sorted(used - files)}"
    assert files <= used, f"diagrams no guide uses: {sorted(files - used)}"
