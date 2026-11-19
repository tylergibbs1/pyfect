"""CHANGELOG.md has one section per version, newest first, and only the top one unreleased.

Merging branches that each add to the unreleased section can leave two copies of it.
"""

import re
import shutil
import subprocess
import tomllib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
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


def _unreleased_headings(text: str) -> list[str]:
    """The ``### `` headings under ``## Unreleased``."""
    _, found, rest = f"\n{text}".partition(f"\n{UNRELEASED}\n")
    if not found:
        return []
    section = rest.split("\n## ", 1)[0]
    return [line[4:].strip() for line in section.splitlines() if line.startswith("### ")]


def _too_early_for_a_minor(text: str, version: str) -> list[str]:
    """Unreleased headings a patch release can't carry, while ``version`` (pyproject's) is
    still in the newest released minor series: the next release would have to be a minor."""
    released = [v for v, when in _sections(text) if when != "unreleased"]
    major, minor, _ = (int(part) for part in version.split("."))
    if not released or (major, minor) != released[0][:2]:
        return []
    return sorted(set(_unreleased_headings(text)) - PATCH_HEADINGS)


def test_unreleased_minor_entries_wait_for_the_minor_version():
    """#175 put a Changed entry on main while the version was 0.6.14, which made the next
    release a minor one and blocked 0.6.x patches. Such entries stay on a -070 branch until
    the release bumps pyproject to 0.7.0."""
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    offenders = _too_early_for_a_minor(_text(), version)
    assert not offenders, (
        f"## Unreleased has {offenders} while pyproject is {version}: the next release would be "
        "a minor one (docs/VERSIONING.md). Keep the change on a -0X0 branch until the minor "
        "release bumps the version"
    )


def test_the_minor_entry_check_waits_for_the_version_bump():
    text = (
        "## Unreleased\n\n### Changed\n\n- a\n\n### Fixed\n\n- b\n\n"
        "## 0.6.14 (2026-11-19)\n\n### Fixed\n\n- c\n"
    )
    assert _too_early_for_a_minor(text, "0.6.14") == ["Changed"]
    assert _too_early_for_a_minor(text.replace("Changed", "Removed"), "0.6.15") == ["Removed"]
    assert _too_early_for_a_minor(text, "0.7.0") == []
    assert _too_early_for_a_minor(text.replace("### Changed", "### Added"), "0.6.14") == []


def _repeated_subheadings(text: str) -> list[str]:
    """``### `` headings that appear twice in one ``## `` section, as ``section / heading``."""
    seen: set[tuple[str, str]] = set()
    repeated: list[str] = []
    section = ""
    for line in text.splitlines():
        if line.startswith("## "):
            section = line
        elif line.startswith("### "):
            if (section, line) in seen:
                repeated.append(f"{section} / {line}")
            seen.add((section, line))
    return repeated


def test_no_section_repeats_a_subheading():
    assert _repeated_subheadings(_text()) == []


def test_the_subheading_check_rejects_a_heading_doubled_within_a_section():
    one = "## Unreleased\n\n### Fixed\n\n- a\n\n## 0.6.10 (2026-11-16)\n\n### Fixed\n"
    assert _repeated_subheadings(one) == []
    doubled = "## Unreleased\n\n### Fixed\n\n- a\n\n### Fixed\n\n- b\n"
    assert _repeated_subheadings(doubled) == ["## Unreleased / ### Fixed"]


_EFFECT_REF = re.compile(r"Effect-TS/effect#(\d+)")


def _repeated_effect_refs(text: str) -> list[str]:
    """Effect PRs cited by more than one entry of the Unreleased section. Each ported Effect fix
    gets one entry, so a second is a copy, such as a union merge keeps when a branch edited
    its entry in a later commit."""
    section = text.split(f"{UNRELEASED}\n", 1)[1].split("\n## ", 1)[0] if UNRELEASED in text else ""
    entries = re.split(r"\n(?=- |### )", section)
    seen: set[str] = set()
    repeated: list[str] = []
    for entry in entries:
        for ref in sorted(set(_EFFECT_REF.findall(entry))):
            if ref in seen and ref not in repeated:
                repeated.append(ref)
            seen.add(ref)
    return repeated


def test_no_two_unreleased_entries_cite_the_same_effect_change():
    assert _repeated_effect_refs(_text()) == []


def test_the_effect_ref_check_rejects_a_copied_entry():
    one = "## Unreleased\n\n### Fixed\n\n- a, as Effect-TS/effect#1 and Effect-TS/effect#1.\n"
    assert _repeated_effect_refs(one) == []
    released = "\n## 0.6.10 (2026-11-16)\n\n### Fixed\n\n- a, as Effect-TS/effect#1.\n"
    assert _repeated_effect_refs(one + released) == []
    copied = one + "\n- a again, as\n  Effect-TS/effect#1.\n"
    assert _repeated_effect_refs(copied) == ["1"]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def test_the_changelog_merges_by_union():
    assert _git(ROOT, "check-attr", "merge", "--", "CHANGELOG.md").strip().endswith(": union")


def test_branches_adding_fixed_entries_merge_without_conflict(tmp_path: Path):
    """Two branches that each add an entry under the same heading merge to both entries."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")
    shutil.copy(ROOT / ".gitattributes", repo / ".gitattributes")
    base = "# Changelog\n\n## Unreleased\n\n### Fixed\n\n- base\n\n## 0.6.10 (2026-11-16)\n"
    changelog = repo / "CHANGELOG.md"
    changelog.write_text(base)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    for branch, entry in (("one", "- one\n"), ("two", "- two\n")):
        _git(repo, "checkout", "-q", "-b", branch, "main")
        changelog.write_text(base.replace("- base\n", f"- base\n\n{entry}"))
        _git(repo, "commit", "-qam", branch)
    _git(repo, "merge", "-q", "--no-edit", "one")
    merged = changelog.read_text()
    assert "- one\n" in merged and "- two\n" in merged
    assert "<<<<<<<" not in merged
    assert _repeated_subheadings(merged) == []


def _released_sections(text: str) -> dict[str, list[str]]:
    """Each released version's heading and its lines."""
    sections: dict[str, list[str]] = {}
    lines: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            lines = sections.setdefault(line, []) if HEADING.match(line) else None
        elif lines is not None:
            lines.append(line)
    return {h: body for h, body in sections.items() if not h.endswith("(unreleased)")}


def _added_to_released(base: str, head: str) -> list[str]:
    """Lines ``head`` adds inside a version ``base`` already released: an entry meant for
    the next release that landed under a shipped one."""
    head_sections = _released_sections(head)
    added: list[str] = []
    for heading, lines in _released_sections(base).items():
        left = Counter(lines)
        for line in head_sections.get(heading, []):
            if left[line] > 0:
                left[line] -= 1
            else:
                added.append(f"{heading}: {line}")
    return added


def test_no_branch_adds_to_a_released_section():
    """Main's CHANGELOG is the released record (CI fetches ``origin/main`` for this)."""
    base = _git(ROOT, "show", "origin/main:CHANGELOG.md")
    assert _added_to_released(base, _text()) == [], "move the entry to ## Unreleased"


def test_the_released_section_check_rejects_an_entry_under_a_shipped_version():
    base = "## Unreleased\n\n### Fixed\n\n- a\n\n## 0.6.12 (2026-11-18)\n\n### Fixed\n\n- b\n"
    late = base.replace("- b\n", "- b\n- c\n")
    assert _added_to_released(base, late) == ["## 0.6.12 (2026-11-18): - c"]
    assert _added_to_released(base, base.replace("- a\n", "- a\n- c\n")) == []
