"""``LogLevel`` renders as Effect's ``LogLevel`` strings (``"Info"``), and
log output spells levels as Effect does, never by the enum member's name."""

import re
from pathlib import Path

import pytest

from pyfect.logger import LogLevel

EFFECT_LABELS = ["All", "Fatal", "Error", "Warn", "Info", "Debug", "Trace", "None"]


@pytest.mark.parametrize(("level", "label"), list(zip(LogLevel, EFFECT_LABELS, strict=True)))
def test_a_level_prints_as_effects_label(level: LogLevel, label: str):
    assert str(level) == label
    assert f"{level}" == label
    assert f"[{level:>6}]" == f"[{label:>6}]"
    assert int(level) == level.value


def test_no_log_output_uses_the_enum_member_name():
    """Effect writes ``logLevel`` (``"Info"``) or ``logLevel.toUpperCase()``;
    a member's ``.name`` (``"INFO"``) only happens to match the latter, so
    every renderer goes through ``str(level)``."""
    src = Path(__file__).parent.parent / "src" / "pyfect"
    offenders = [
        f"{path.relative_to(src)}:{n}"
        for path in src.rglob("*.py")
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if re.search(r"(log_level|level)\.name\b", line)
    ]
    assert offenders == []
