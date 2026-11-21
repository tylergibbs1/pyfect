"""Cut a release: move the fragments in changes/ into CHANGELOG.md and set the version.

    uv run python scripts/release.py 0.6.19            # dated today (UTC)
    uv run python scripts/release.py 0.7.0 --date 2026-12-01

A fragment is one changelog entry, ``changes/<slug>.<section>.md``, its body the entry's
Markdown starting with ``- ``. Branches add fragments and never edit CHANGELOG.md, so a release
merged in the meantime can't move their entries into the version it shipped.
"""

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal, NamedTuple, cast, get_args

ROOT = Path(__file__).resolve().parent.parent
CHANGES = "changes"

type Section = Literal["added", "changed", "deprecated", "removed", "fixed", "performance", "docs"]
SECTIONS: tuple[Section, ...] = get_args(Section.__value__)
"""In the order a release lists them."""
PATCH_SECTIONS: frozenset[Section] = frozenset(
    {"added", "deprecated", "fixed", "performance", "docs"}
)
"""What a patch release may carry (docs/VERSIONING.md); the rest wait for a minor one."""
TITLES: dict[Section, str] = {section: section.capitalize() for section in SECTIONS}

_NAME = re.compile(rf"([a-z0-9]+(?:[-_][a-z0-9]+)*)\.({'|'.join(SECTIONS)})\.md")
_HEADER = "# Changelog\n\n"
_VERSION_HEADING = re.compile(r"^## (\d+)\.(\d+)\.(\d+) \(\d{4}-\d{2}-\d{2}\)$", re.MULTILINE)
_PYPROJECT_VERSION = re.compile(r'^version = "[^"]*"$', re.MULTILINE)


class Version(NamedTuple):
    major: int
    minor: int
    patch: int

    @staticmethod
    def parse(text: str) -> "Version":
        parts = text.split(".")
        if len(parts) != 3 or not all(part.isascii() and part.isdigit() for part in parts):
            raise ReleaseError(f"{text!r} is not a version like 0.6.19")
        major, minor, patch = (int(part) for part in parts)
        return Version(major, minor, patch)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


class ReleaseError(Exception):
    """A fragment, the changelog or the version is not fit to release."""


@dataclass(frozen=True)
class Fragment:
    name: str
    slug: str
    section: Section
    body: str


def parse_fragment(name: str, body: str) -> Fragment:
    """One file of changes/, checked: a name ``<slug>.<section>.md`` and one entry, a ``- ``
    line and its continuation lines indented by two spaces, ending in one newline."""
    match = _NAME.fullmatch(name)
    if match is None:
        raise ReleaseError(
            f"{CHANGES}/{name}: name it <slug>.<section>.md, the slug lowercase letters, digits,"
            f" '-' and '_', the section one of {', '.join(SECTIONS)}"
        )
    lines = body.split("\n")
    if not body.startswith("- ") or lines[-1] != "" or lines[-2].strip() == "":
        raise ReleaseError(f"{CHANGES}/{name}: an entry starts with '- ' and ends in one newline")
    stray = [line for line in lines[1:-1] if line and not line.startswith("  ")]
    if stray:
        raise ReleaseError(
            f"{CHANGES}/{name}: one entry per fragment, its later lines indented by two spaces:"
            f" {stray[0]!r}"
        )
    return Fragment(name, match[1], cast("Section", match[2]), body)


def read_fragments(root: Path) -> list[Fragment]:
    """The fragments in ``root``/changes/, in the order a release lists them."""
    directory = root / CHANGES
    files = sorted(directory.iterdir()) if directory.is_dir() else []
    fragments = [parse_fragment(path.name, path.read_text(encoding="utf-8")) for path in files]
    return sorted(fragments, key=lambda f: (SECTIONS.index(f.section), f.slug))


def render(version: Version, day: date, fragments: Iterable[Fragment]) -> str:
    """The release's section of CHANGELOG.md, ending in the blank line before the next one."""
    by_section: dict[Section, list[str]] = {}
    for fragment in fragments:
        by_section.setdefault(fragment.section, []).append(fragment.body)
    blocks = [
        f"### {TITLES[section]}\n\n" + "".join(by_section[section]) + "\n"
        for section in SECTIONS
        if section in by_section
    ]
    return f"## {version} ({day.isoformat()})\n\n" + "".join(blocks)


def released_versions(changelog: str) -> list[Version]:
    return [Version(int(a), int(b), int(c)) for a, b, c in _VERSION_HEADING.findall(changelog)]


def too_early_for_a_minor(fragments: Iterable[Fragment], version: Version) -> list[str]:
    """Fragments a release of ``version`` can't carry: a patch release only fixes, adds,
    deprecates, speeds up or documents."""
    if version.patch == 0:
        return []
    return [f.name for f in fragments if f.section not in PATCH_SECTIONS]


def release(root: Path, version: Version, day: date) -> list[Fragment]:
    """Write ``version``'s section from the fragments into CHANGELOG.md, delete them and set
    pyproject's version. Returns the fragments it released."""
    changelog_path = root / "CHANGELOG.md"
    pyproject_path = root / "pyproject.toml"
    changelog = changelog_path.read_text(encoding="utf-8")
    if not changelog.startswith(_HEADER):
        raise ReleaseError(f"CHANGELOG.md should start with {_HEADER!r}")
    released = released_versions(changelog)
    if released and version <= released[0]:
        raise ReleaseError(f"{version} is not after the newest release, {released[0]}")
    fragments = read_fragments(root)
    if not fragments:
        raise ReleaseError(f"{CHANGES}/ holds no fragments: there is nothing to release")
    early = too_early_for_a_minor(fragments, version)
    if early:
        raise ReleaseError(
            f"{version} is a patch release, and these need a minor one (docs/VERSIONING.md): "
            + ", ".join(early)
        )
    pyproject = pyproject_path.read_text(encoding="utf-8")
    updated, count = _PYPROJECT_VERSION.subn(f'version = "{version}"', pyproject, count=1)
    if count != 1:
        raise ReleaseError('pyproject.toml has no version = "..." line')
    section = render(version, day, fragments)
    changelog_path.write_text(_HEADER + section + changelog[len(_HEADER) :], encoding="utf-8")
    pyproject_path.write_text(updated, encoding="utf-8")
    for fragment in fragments:
        (root / CHANGES / fragment.name).unlink()
    return fragments


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="Release the fragments in changes/")
    parser.add_argument("version", help="the version to release, such as 0.6.19")
    parser.add_argument("--date", help="the release date, YYYY-MM-DD (default: today, UTC)")
    args = parser.parse_args(argv)
    try:
        version = Version.parse(args.version)
        day = date.fromisoformat(args.date) if args.date else datetime.now(UTC).date()
        fragments = release(ROOT, version, day)
    except (ReleaseError, ValueError) as error:
        print(f"release.py: {error}", file=sys.stderr)
        return 1
    subprocess.run(["uv", "lock"], cwd=ROOT, check=True)
    print(f"{version}: {len(fragments)} entries in CHANGELOG.md; pyproject and uv.lock updated")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
