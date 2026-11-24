"""The changelog: one fragment per entry in changes/, and CHANGELOG.md, which only a release
commit changes (``scripts/release.py``), one section per version, newest first.

Branches used to add entries under ``## Unreleased`` in CHANGELOG.md; a release merged
meanwhile renamed that heading, and a rebase slid the branch's entry into the shipped version.
A fragment is a file of its own, so no rebase can move it.
"""

import importlib.util
import re
import subprocess
import sys
import tomllib
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release", ROOT / "scripts" / "release.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["release"] = module
    spec.loader.exec_module(module)
    return module


release = _script()
Version = release.Version
HEADING = re.compile(r"^## (\d+)\.(\d+)\.(\d+) \((\d{4}-\d{2}-\d{2})\)$")
# docs/VERSIONING.md: a patch release only fixes, adds, deprecates, speeds up or documents.
PATCH_HEADINGS = {release.TITLES[section] for section in release.PATCH_SECTIONS}
POLICY_SINCE = Version(0, 5, 5)


def _text() -> str:
    return CHANGELOG.read_text(encoding="utf-8")


def _pyproject_version() -> Version:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return Version.parse(pyproject["project"]["version"])


def _sections(text: str) -> dict[Version, str]:
    """Each version's section, its heading line to the next ``## `` heading."""
    found: dict[Version, str] = {}
    for chunk in re.split(r"(?m)^(?=## )", text)[1:]:
        heading = HEADING.match(chunk.split("\n", 1)[0])
        if heading:
            found[Version(*(int(part) for part in heading.groups()[:3]))] = chunk
    return found


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], check=True, capture_output=True, text=True
    ).stdout


# CHANGELOG.md


def test_every_heading_is_a_released_version():
    """Entries waiting for a release are fragments in changes/, not an Unreleased section."""
    others = [
        line for line in _text().splitlines() if line.startswith("## ") and not HEADING.match(line)
    ]
    assert others == [], "add each entry as changes/<slug>.<section>.md (docs/VERSIONING.md)"


def test_versions_are_unique_and_newest_first():
    versions = [
        Version(int(a), int(b), int(c))
        for a, b, c in re.findall(r"^## (\d+)\.(\d+)\.(\d+) ", _text(), re.MULTILINE)
    ]
    assert versions == sorted(set(versions), reverse=True)


def _subheadings(section: str) -> list[str]:
    return [line[4:].strip() for line in section.splitlines() if line.startswith("### ")]


def test_patch_releases_only_fix_add_deprecate_or_document():
    offenders = {
        str(version): sorted(set(_subheadings(section)) - PATCH_HEADINGS)
        for version, section in _sections(_text()).items()
        if version > POLICY_SINCE
        and version.patch != 0
        and set(_subheadings(section)) - PATCH_HEADINGS
    }
    assert not offenders, (
        f"these patch sections need a minor release (docs/VERSIONING.md): {offenders}"
    )


def _repeated_subheadings(text: str) -> list[str]:
    """``### `` headings that appear twice in one version, as ``version / heading``."""
    return [
        f"{version} / {heading}"
        for version, section in _sections(text).items()
        for heading in sorted(set(_subheadings(section)))
        if _subheadings(section).count(heading) > 1
    ]


def test_no_section_repeats_a_subheading():
    assert _repeated_subheadings(_text()) == []


def test_the_subheading_check_rejects_a_heading_doubled_within_a_section():
    one = "## 0.6.11 (2026-11-17)\n\n### Fixed\n\n- a\n\n## 0.6.10 (2026-11-16)\n\n### Fixed\n"
    assert _repeated_subheadings(one) == []
    doubled = "## 0.6.11 (2026-11-17)\n\n### Fixed\n\n- a\n\n### Fixed\n\n- b\n"
    assert _repeated_subheadings(doubled) == ["0.6.11 / Fixed"]


def _above_the_sections(text: str) -> str:
    """The text before the first ``## `` heading (an Unreleased one fails its own test)."""
    first = re.search(r"(?m)^## ", text)
    return text[: first.start()] if first else text


def _edits_outside_a_release(
    base: str, head: str, version: Version, fragments: list[str]
) -> list[str]:
    """How ``head``'s CHANGELOG.md differs from ``base``'s (main's) other than by a release:
    one new section on top, for pyproject's ``version``, with every fragment moved into it."""
    old, new = _sections(base), _sections(head)
    problems = [f"{v} was edited after its release" for v in new if v in old and new[v] != old[v]]
    if _above_the_sections(head) != _above_the_sections(base):
        problems.append("the text above the sections changed")
    added = [v for v in new if v not in old]
    if added and (added != [version] or next(iter(new)) != version):
        problems.append(f"{added} added, where a release adds one section on top, for {version}")
    if added and fragments:
        problems.append(f"the release left {fragments} in changes/: run scripts/release.py again")
    return problems


def test_only_a_release_changes_the_changelog():
    """CHANGELOG.md changes only in a release commit, made by ``scripts/release.py``. CI fetches
    ``origin/main`` for this; a branch behind main may lack main's newest sections."""
    problems = _edits_outside_a_release(
        _git("show", "origin/main:CHANGELOG.md"),
        _text(),
        _pyproject_version(),
        release.read_changes(ROOT).names(),
    )
    assert problems == [], (
        "CHANGELOG.md changes only in a release commit (scripts/release.py X.Y.Z). "
        f"For an entry, add changes/<slug>.<section>.md instead: {problems}"
    )


def test_the_release_check_rejects_any_other_edit():
    base = "# Changelog\n\n## 0.6.12 (2026-11-18)\n\n### Fixed\n\n- b\n"
    shipped = "# Changelog\n\n## 0.6.13 (2026-11-19)\n\n### Fixed\n\n- c\n\n" + base[13:]
    v12, v13 = Version(0, 6, 12), Version(0, 6, 13)
    assert _edits_outside_a_release(base, base, v12, ["a.fixed.md"]) == []
    assert _edits_outside_a_release(base, shipped, v13, []) == []
    assert _edits_outside_a_release(shipped, base, v12, ["a.fixed.md"]) == []  # behind main
    late = base.replace("- b\n", "- b\n- c\n")
    assert _edits_outside_a_release(base, late, v12, []) == ["0.6.12 was edited after its release"]
    intro = base.replace("\n\n## 0.6.12", "\n\nAll the changes.\n\n## 0.6.12")
    assert _edits_outside_a_release(base, intro, v12, []) == ["the text above the sections changed"]
    assert _edits_outside_a_release(base, shipped, v12, []) == [
        f"{[v13]} added, where a release adds one section on top, for {v12}"
    ]
    assert _edits_outside_a_release(base, shipped, v13, ["a.fixed.md"]) == [
        "the release left ['a.fixed.md'] in changes/: run scripts/release.py again"
    ]


# Fragments


def test_every_file_in_changes_is_a_fragment():
    release.read_changes(ROOT)


def test_a_none_fragment_is_a_note_that_a_change_needs_no_entry():
    note = release.parse_fragment("refactor.none.md", "- only moves code\n")
    assert note == release.NoEntry("refactor.none.md", "- only moves code\n")
    with pytest.raises(release.ReleaseError, match=re.escape("starts with '- '")):
        release.parse_fragment("refactor.none.md", "only moves code\n")


@pytest.mark.parametrize(
    ("name", "body", "message"),
    [
        ("fix.md", "- a\n", "name it <slug>.<section>.md"),
        ("fix.breaking.md", "- a\n", "name it <slug>.<section>.md"),
        ("Fix.fixed.md", "- a\n", "name it <slug>.<section>.md"),
        ("fix.fixed.md", "a\n", "starts with '- '"),
        ("fix.fixed.md", "- a", "ends in one newline"),
        ("fix.fixed.md", "- a\n\n", "ends in one newline"),
        ("fix.fixed.md", "- a\n- b\n", "one entry per fragment"),
        ("fix.fixed.md", "- a\n### Fixed\n", "one entry per fragment"),
    ],
)
def test_a_malformed_fragment_is_refused(name: str, body: str, message: str):
    with pytest.raises(release.ReleaseError, match=re.escape(message)):
        release.parse_fragment(name, body)


def test_an_entry_may_run_over_several_lines_and_paragraphs():
    body = "- a\n  b\n\n  c\n"
    assert release.parse_fragment("a-b_2.performance.md", body).body == body


def _waiting_for_a_minor(fragments: list[str], version: Version, newest: Version) -> list[str]:
    """Fragments the next release can't carry while pyproject's ``version`` is still in the
    newest released minor series: that release would have to be a minor one."""
    if version[:2] != newest[:2]:
        return []
    parsed = [release.parse_fragment(name, "- a\n") for name in fragments]
    entries = [fragment for fragment in parsed if isinstance(fragment, release.Fragment)]
    return release.too_early_for_a_minor(entries, Version(*newest[:2], newest.patch + 1))


def test_minor_fragments_wait_for_the_minor_version():
    """#175 put a Changed entry on main while the version was 0.6.14, which made the next
    release a minor one and blocked 0.6.x patches. Such fragments stay on a -070 branch until
    the 0.7.0 release commit carries them."""
    version = _pyproject_version()
    offenders = _waiting_for_a_minor(
        release.read_changes(ROOT).names(),
        version,
        release.released_versions(_text())[0],
    )
    assert not offenders, (
        f"{offenders} while pyproject is {version}: the next release would be a minor one "
        "(docs/VERSIONING.md). Keep the change on a -0X0 branch until the minor release"
    )


def test_the_minor_fragment_check_waits_for_the_version_bump():
    v14 = Version(0, 6, 14)
    names = ["a.changed.md", "b.fixed.md"]
    assert _waiting_for_a_minor(names, v14, v14) == ["a.changed.md"]
    assert _waiting_for_a_minor(["a.removed.md"], v14, v14) == ["a.removed.md"]
    assert _waiting_for_a_minor(names, Version(0, 7, 0), v14) == []
    assert _waiting_for_a_minor(["a.added.md"], v14, v14) == []
    # A note that a change needs no entry never makes a release a minor one.
    assert _waiting_for_a_minor(["a.none.md", "b.changed.md"], v14, v14) == ["b.changed.md"]


_EFFECT_REF = re.compile(r"Effect-TS/effect#(\d+)")


def _repeated_effect_refs(bodies: list[str]) -> list[str]:
    """Effect PRs cited by more than one fragment. Each ported Effect fix gets one entry, so a
    second is a copy."""
    seen: set[str] = set()
    repeated: list[str] = []
    for body in bodies:
        for ref in sorted(set(_EFFECT_REF.findall(body))):
            if ref in seen and ref not in repeated:
                repeated.append(ref)
            seen.add(ref)
    return repeated


def test_no_two_fragments_cite_the_same_effect_change():
    assert _repeated_effect_refs([f.body for f in release.read_changes(ROOT).entries]) == []


def test_the_effect_ref_check_rejects_a_copied_entry():
    one = "- a, as Effect-TS/effect#1 and Effect-TS/effect#1.\n"
    assert _repeated_effect_refs([one]) == []
    assert _repeated_effect_refs([one, "- a again, as\n  Effect-TS/effect#1.\n"]) == ["1"]


# scripts/release.py


def _repo(tmp_path: Path, changelog: str, fragments: dict[str, str]) -> Path:
    (tmp_path / "CHANGELOG.md").write_text(changelog)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.6.12"\n')
    (tmp_path / "changes").mkdir()
    for name, body in fragments.items():
        (tmp_path / "changes" / name).write_text(body)
    return tmp_path


def _as_fragments(section: str) -> dict[str, str]:
    """A released section's entries as fragments, named to keep their order."""
    fragments: dict[str, str] = {}
    heading = ""
    for chunk in re.split(r"(?m)^(?=### |- )", section)[1:]:
        if chunk.startswith("### "):
            heading = chunk[4:].split("\n", 1)[0].lower()
        else:
            fragments[f"e{len(fragments):03d}.{heading}.md"] = chunk.rstrip("\n") + "\n"
    return fragments


@pytest.mark.parametrize("version", ["0.6.16", "0.6.17", "0.6.18", "0.6.19"])
def test_a_release_rebuilds_from_its_fragments(tmp_path: Path, version: str):
    """The script writes what was written by hand before it."""
    text = _text()
    sections = _sections(text)
    section = sections[Version.parse(version)]
    older = text[text.index(section) + len(section) :]
    day = date.fromisoformat(section[len(f"## {version} (") :][:10])
    repo = _repo(tmp_path, "# Changelog\n\n" + older, _as_fragments(section))
    release.release(repo, Version.parse(version), day)
    assert (repo / "CHANGELOG.md").read_text() == "# Changelog\n\n" + section + older


def test_a_release_moves_the_fragments_and_sets_the_version(tmp_path: Path):
    old = "# Changelog\n\n## 0.6.12 (2026-11-18)\n\n### Fixed\n\n- old\n"
    repo = _repo(
        tmp_path,
        old,
        {"z.fixed.md": "- z\n", "a.fixed.md": "- a\n  more\n", "doc.docs.md": "- d\n"},
    )
    release.release(repo, Version(0, 6, 13), date(2026, 11, 19))
    assert (repo / "CHANGELOG.md").read_text() == (
        "# Changelog\n\n## 0.6.13 (2026-11-19)\n\n### Fixed\n\n- a\n  more\n- z\n\n"
        "### Docs\n\n- d\n\n## 0.6.12 (2026-11-18)\n\n### Fixed\n\n- old\n"
    )
    assert list((repo / "changes").iterdir()) == []
    assert 'version = "0.6.13"' in (repo / "pyproject.toml").read_text()


def test_a_patch_release_with_a_changed_fragment_fails(tmp_path: Path):
    old = "# Changelog\n\n## 0.6.12 (2026-11-18)\n\n### Fixed\n\n- old\n"
    repo = _repo(tmp_path, old, {"a.changed.md": "- a\n", "b.fixed.md": "- b\n"})
    with pytest.raises(release.ReleaseError, match=r"0\.6\.13 is a patch release.*a\.changed\.md"):
        release.release(repo, Version(0, 6, 13), date(2026, 11, 19))
    assert (repo / "CHANGELOG.md").read_text() == old
    release.release(repo, Version(0, 7, 0), date(2026, 11, 19))
    assert (
        (repo / "CHANGELOG.md")
        .read_text()
        .startswith(
            "# Changelog\n\n## 0.7.0 (2026-11-19)\n\n### Changed\n\n- a\n\n### Fixed\n\n- b\n\n"
        )
    )


def test_a_release_deletes_the_notes_without_an_entry(tmp_path: Path):
    old = "# Changelog\n\n## 0.6.12 (2026-11-18)\n\n### Fixed\n\n- old\n"
    repo = _repo(tmp_path, old, {"a.fixed.md": "- a\n", "r.none.md": "- a refactor\n"})
    released = release.release(repo, Version(0, 6, 13), date(2026, 11, 19))
    assert [fragment.name for fragment in released] == ["a.fixed.md"]
    assert (repo / "CHANGELOG.md").read_text() == (
        "# Changelog\n\n## 0.6.13 (2026-11-19)\n\n### Fixed\n\n- a\n\n"
        + old[len("# Changelog\n\n") :]
    )
    assert list((repo / "changes").iterdir()) == []


@pytest.mark.parametrize(
    ("version", "fragments", "message"),
    [
        ("0.6.12", {"a.fixed.md": "- a\n"}, "not after the newest release, 0.6.12"),
        ("0.6.13", {}, "nothing to release"),
        ("0.6.13", {"r.none.md": "- a refactor\n"}, "nothing to release"),
    ],
)
def test_a_release_refuses_an_old_version_or_no_fragments(
    tmp_path: Path, version: str, fragments: dict[str, str], message: str
):
    repo = _repo(tmp_path, "# Changelog\n\n## 0.6.12 (2026-11-18)\n\n### Fixed\n\n- b\n", fragments)
    with pytest.raises(release.ReleaseError, match=re.escape(message)):
        release.release(repo, Version.parse(version), date(2026, 11, 19))


@pytest.mark.parametrize("text", ["0.6", "0.6.x", "v0.6.1", "0.6.1.2", "0.6.\u0661"])
def test_a_version_is_three_numbers(text: str):
    with pytest.raises(release.ReleaseError, match="is not a version"):
        Version.parse(text)


def test_a_carry_rebuilds_0_6_32_from_the_unpublished_0_6_31(tmp_path: Path):
    """0.6.31 was tagged but never published; 0.6.32, folded together by hand, is what
    ``--carry`` writes from 0.6.31's section and only a note that a change needs no entry."""
    text = _text()
    section = _sections(text)[Version(0, 6, 32)]
    older = text[text.index(section) + len(section) :]
    note = (
        "0.6.31 was tagged but never published: a test timed out in its release run. 0.6.32"
        " carries its changes.\n\n"
    )
    unpublished = section.replace("## 0.6.32", "## 0.6.31", 1).replace(note, "", 1)
    repo = _repo(tmp_path, "# Changelog\n\n" + unpublished + older, {})
    (repo / "changes" / "tests.none.md").write_text("- test speed\n")
    carry = release.Carry(Version(0, 6, 31), "a test timed out in its release run")
    release.release(repo, Version(0, 6, 32), date(2026, 11, 24), carry)
    assert (repo / "CHANGELOG.md").read_text() == "# Changelog\n\n" + section + older
    assert list((repo / "changes").iterdir()) == []
    assert 'version = "0.6.32"' in (repo / "pyproject.toml").read_text()


_UNPUBLISHED = (
    "# Changelog\n\n## 0.6.13 (2026-11-19)\n\n### Fixed\n\n- old fix\n  more\n\n"
    "### Docs\n\n- old doc\n\n## 0.6.12 (2026-11-18)\n\n### Fixed\n\n- b\n"
)


def test_a_carry_merges_the_sections_in_order_with_the_note_first(tmp_path: Path):
    repo = _repo(tmp_path, _UNPUBLISHED, {"a.added.md": "- new\n", "f.fixed.md": "- new fix\n"})
    carry = release.Carry(Version(0, 6, 13), "its release run failed.")
    released = release.release(repo, Version(0, 6, 14), date(2026, 11, 20), carry)
    assert len(released) == 4
    assert (repo / "CHANGELOG.md").read_text() == (
        "# Changelog\n\n## 0.6.14 (2026-11-20)\n\n"
        "0.6.13 was tagged but never published: its release run failed. 0.6.14 carries its"
        " changes.\n\n"
        "### Added\n\n- new\n\n"
        "### Fixed\n\n- old fix\n  more\n- new fix\n\n"
        "### Docs\n\n- old doc\n\n"
        "## 0.6.12 (2026-11-18)\n\n### Fixed\n\n- b\n"
    )
    assert list((repo / "changes").iterdir()) == []


def test_a_carry_needs_only_notes_without_an_entry(tmp_path: Path):
    repo = _repo(tmp_path, _UNPUBLISHED, {"r.none.md": "- a refactor\n"})
    carry = release.Carry(Version(0, 6, 13), "a test timed out")
    release.release(repo, Version(0, 6, 14), date(2026, 11, 20), carry)
    assert (
        (repo / "CHANGELOG.md")
        .read_text()
        .startswith(
            "# Changelog\n\n## 0.6.14 (2026-11-20)\n\n0.6.13 was tagged but never published:"
            " a test timed out. 0.6.14 carries its changes.\n\n### Fixed\n\n- old fix\n  more\n\n"
            "### Docs\n\n- old doc\n\n## 0.6.12"
        )
    )
    assert list((repo / "changes").iterdir()) == []


@pytest.mark.parametrize(
    ("carried", "reason", "message"),
    [
        ("0.6.12", "x", "--carry 0.6.12 is not the newest release, 0.6.13"),
        ("0.6.13", " ", "say why 0.6.13 was never published"),
    ],
)
def test_a_carry_refuses_an_older_version_or_no_reason(
    tmp_path: Path, carried: str, reason: str, message: str
):
    repo = _repo(tmp_path, _UNPUBLISHED, {})
    carry = release.Carry(Version.parse(carried), reason)
    with pytest.raises(release.ReleaseError, match=re.escape(message)):
        release.release(repo, Version(0, 6, 14), date(2026, 11, 20), carry)
    assert (repo / "CHANGELOG.md").read_text() == _UNPUBLISHED


def test_carry_and_reason_go_together():
    with pytest.raises(SystemExit):
        release.main(["0.6.14", "--carry", "0.6.13"])
