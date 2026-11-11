"""CHANGELOG.md has one section per version, newest first, and only the top one unreleased.

Merging branches that each add to the unreleased section can leave two copies of it.
"""

import re
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
HEADING = re.compile(r"^## (\d+)\.(\d+)\.(\d+) \((unreleased|\d{4}-\d{2}-\d{2})\)$", re.M)


def _sections() -> list[tuple[tuple[int, int, int], str]]:
    return [
        ((int(a), int(b), int(c)), when)
        for a, b, c, when in HEADING.findall(CHANGELOG.read_text(encoding="utf-8"))
    ]


def test_every_version_heading_parses():
    text = CHANGELOG.read_text(encoding="utf-8")
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert len(headings) == len(_sections()), [h for h in headings if not HEADING.match(h)]


def test_versions_are_unique_and_newest_first():
    versions = [v for v, _ in _sections()]
    assert versions == sorted(set(versions), reverse=True)


def test_only_the_top_section_is_unreleased():
    unreleased = [i for i, (_, when) in enumerate(_sections()) if when == "unreleased"]
    assert unreleased in ([], [0])
