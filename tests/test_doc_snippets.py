"""The guides' Python code runs, and only comes from checked files.

Every Python block in `website/content/docs` is an `<include>` of a file under
`website/snippets`, which pyright checks and these tests run (the site is built
from `website/` alone, so guides can't include files outside it):
a snippet asserts its own results, and `test_*.py` snippets are pytest files.
"""

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


def guide_files() -> list[Path]:
    return sorted(GUIDES.rglob("*.mdx"))


def included_files(guide: Path) -> list[Path]:
    """The files a guide includes, resolved as Fumadocs does: relative to the
    guide, with any `#region` suffix removed."""
    targets = INCLUDE.findall(guide.read_text())
    return [(guide.parent / target.split("#")[0]).resolve() for target in targets]


def run(*args: str) -> subprocess.CompletedProcess[str]:
    # -P: don't put the snippet's directory on sys.path, as `python file.py` would.
    return subprocess.run(
        [sys.executable, "-P", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=ROOT,
    )


def name(path: Path) -> str:
    return str(path.relative_to(SNIPPETS))


SCRIPTS = [p for p in snippet_files() if not p.name.startswith("test_")]
TESTS = [p for p in snippet_files() if p.name.startswith("test_")]


@pytest.mark.parametrize("path", SCRIPTS, ids=name)
def test_snippet_runs(path: Path):
    done = run(str(path))
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("path", TESTS, ids=name)
def test_snippet_tests_pass(path: Path):
    done = run("-m", "pytest", "-q", "-p", "no:cacheprovider", str(path))
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
    unused = [name(p) for p in snippet_files() if p.resolve() not in used]
    assert not unused, f"snippets no guide includes: {unused}"
