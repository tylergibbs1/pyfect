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


# docs/VERSIONING.md: a patch release only fixes, adds, deprecates, speeds up or documents.
PATCH_HEADINGS = {"Fixed", "Added", "Deprecated", "Performance", "Docs"}
POLICY_SINCE = (0, 5, 5)


def _headings_by_version() -> dict[tuple[int, int, int], list[str]]:
    text = CHANGELOG.read_text(encoding="utf-8")
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
