"""CHANGELOG.md has one section per version, newest first, and only the top one unreleased.

Merging branches that each add to the unreleased section can leave two copies of it.
"""

import re
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
HEADING = re.compile(r"^## (\d+)\.(\d+)\.(\d+) \((unreleased|\d{4}-\d{2}-\d{2})\)$", re.MULTILINE)
# Entries waiting for a release go under this heading; the release gives them their version.
UNRELEASED = "## Unreleased"


def _text() -> str:
    return CHANGELOG.read_text(encoding="utf-8")


def _headings(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("## ")]


def _sections(text: str) -> list[tuple[tuple[int, int, int], str]]:
    return [((int(a), int(b), int(c)), when) for a, b, c, when in HEADING.findall(text)]


def _unparsed_headings(text: str) -> list[str]:
    return [h for h in _headings(text) if h != UNRELEASED and not HEADING.match(h)]


def _unreleased_positions(text: str) -> list[int]:
    return [
        i
        for i, heading in enumerate(_headings(text))
        if heading == UNRELEASED or heading.endswith("(unreleased)")
    ]


def test_every_version_heading_parses():
    assert _unparsed_headings(_text()) == []


def test_versions_are_unique_and_newest_first():
    versions = [v for v, _ in _sections(_text())]
    assert versions == sorted(set(versions), reverse=True)


def test_only_the_top_section_is_unreleased():
    assert _unreleased_positions(_text()) in ([], [0])


def test_the_section_checks_reject_a_misplaced_or_doubled_unreleased_section():
    released = "## 0.6.10 (2026-11-16)\n\n## 0.6.9 (2026-11-16)\n"
    assert _unparsed_headings("## Unreleased\n\n" + released) == []
    assert _unreleased_positions("## Unreleased\n\n" + released) == [0]
    assert _unreleased_positions(released + "\n## Unreleased\n") == [2]
    assert _unreleased_positions("## Unreleased\n\n## 0.6.11 (unreleased)\n" + released) == [0, 1]
    assert _unparsed_headings("## unreleased\n\n## 0.6.10\n") == ["## unreleased", "## 0.6.10"]


# docs/VERSIONING.md: a patch release only fixes, adds, deprecates, speeds up or documents.
PATCH_HEADINGS = {"Fixed", "Added", "Deprecated", "Performance", "Docs"}
POLICY_SINCE = (0, 5, 5)


def _headings_by_version() -> dict[tuple[int, int, int], list[str]]:
    text = _text()
    found: dict[tuple[int, int, int], list[str]] = {}
    version: tuple[int, int, int] | None = None
    for line in text.splitlines():
        heading = HEADING.match(line)
        if heading:
            a, b, c, _ = heading.groups()
            version = (int(a), int(b), int(c))
            found[version] = []
        elif line.startswith("### ") and version is not None:
            found[version].append(line[4:].strip())
    return found


def test_patch_releases_only_fix_add_deprecate_or_document():
    offenders = {
        ".".join(map(str, version)): sorted(set(headings) - PATCH_HEADINGS)
        for version, headings in _headings_by_version().items()
        if version > POLICY_SINCE and version[2] != 0 and set(headings) - PATCH_HEADINGS
    }
    assert not offenders, (
        "these patch sections need a minor release (docs/VERSIONING.md), "
        f"or the entries belong under Fixed / Added / Deprecated: {offenders}"
    )
