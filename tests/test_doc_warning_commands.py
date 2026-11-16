"""Every command the Durations section gives for failing on bare-number durations does fail.

Python reads `-W` and `PYTHONWARNINGS` at startup, before pyfect is imported, so a category
such as `pyfect.duration.BareNumberDurationWarning` is "Invalid -W option ignored" and the run
exits 0. 0.6.7 documented that form; this test runs each documented command on a program
that passes a bare number and requires a non-zero exit naming the warning."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "website" / "content" / "docs" / "schedules.mdx"
DOCUMENTS = [
    ROOT / "README.md",
    *(ROOT / "docs").glob("*.md"),
    *(ROOT / "website" / "content").rglob("*.mdx"),
    *(ROOT / "src" / "pyfect").rglob("*.py"),
]

_FAIL_BLOCK = re.compile(r'```sh title="Fail on bare durations"\n(?P<body>.*?)```', re.DOTALL)
_PYTEST_CONFIG = re.compile(r'```toml title="pyproject.toml"\n(?P<body>.*?)```', re.DOTALL)
_BARE = "import pyfect as fx\n\nfx.sleep(2)\n"
_TEST = "import pyfect as fx\n\n\ndef test_it():\n    fx.sleep(2)\n"


def _section() -> str:
    text = PAGE.read_text()
    start = text.index("To find the bare numbers")
    return text[start : text.index("\n## ", start)]


def _commands() -> list[str]:
    match = _FAIL_BLOCK.search(_section())
    assert match, "the Durations section has no `Fail on bare durations` sh block"
    return [line for line in match["body"].splitlines() if line.strip()]


def test_the_section_documents_a_command_for_python_and_for_pytest():
    commands = _commands()
    assert any(" app.py" in command for command in commands)
    assert any("pytest" in command for command in commands)


@pytest.mark.parametrize("command", _commands())
def test_each_documented_command_fails_on_a_bare_duration(command: str, tmp_path: Path):
    config = _PYTEST_CONFIG.search(_section())
    assert config
    (tmp_path / "pyproject.toml").write_text(config["body"])
    (tmp_path / "app.py").write_text(_BARE)
    (tmp_path / "test_app.py").write_text(_TEST)
    python = f'"{sys.executable}"'
    runnable = re.sub(r"\bpytest\b", f"{python} -m pytest -p no:cacheprovider", command)
    runnable = re.sub(r"\bpython\b(?= )", python, runnable, count=1)
    result = subprocess.run(
        runnable, check=False, shell=True, cwd=tmp_path, capture_output=True, text=True, timeout=120
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "BareNumberDurationWarning" in output, output
    assert "Invalid -W option" not in output, output


def test_no_document_names_a_pyfect_category_in_a_python_warning_option():
    # pytest's `filterwarnings` imports the category, so it may name one; `-W` and
    # PYTHONWARNINGS may not.
    option = re.compile(r"(?:-W\s*|PYTHONWARNINGS=)['\"]?[^'\"\s`]*:pyfect\.")
    offenders = [
        f"{path.relative_to(ROOT)}:{number}: {line.strip()}"
        for path in DOCUMENTS
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if option.search(line)
    ]
    assert offenders == []
