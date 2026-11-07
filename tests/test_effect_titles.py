"""Every ``it`` / ``test`` title in Effect's checkout is ported, or omitted with a reason.

A title counts as ported only by a test that names its Effect file. The checkout is
``$PYFECT_EFFECT_REF`` (Effect's repository root), or else ``../pyfect-ref/effect`` beside the
repository; the module is skipped without one, as in CI. See ``_effect_titles.py`` for what
counts as ported and ``_effect_title_omissions.py`` for the list.
"""

from __future__ import annotations

import os
from collections import defaultdict
from fnmatch import fnmatch
from pathlib import Path

import pytest
from _effect_title_omissions import OMISSIONS, reason_for
from _effect_titles import (
    Ports,
    ambiguous_mentions,
    docstrings,
    effect_test_files,
    is_noted_as_omitted,
    is_ported,
    read_ports,
    titles_in_source,
)

_TESTS = Path(__file__).parent
_CHECKOUT = Path(
    os.environ.get("PYFECT_EFFECT_REF") or _TESTS.parent.parent / "pyfect-ref" / "effect"
)
_PACKAGES = _CHECKOUT / "packages"

pytestmark = pytest.mark.skipif(
    not _PACKAGES.is_dir(),
    reason=f"no Effect checkout at {_CHECKOUT}; set PYFECT_EFFECT_REF to Effect's repository",
)


@pytest.fixture(scope="module")
def effect_files() -> dict[str, Path]:
    return {path.relative_to(_PACKAGES).as_posix(): path for path in effect_test_files(_PACKAGES)}


def _test_modules() -> list[Path]:
    # The omission list's own patterns are strings too; they must not count as ports of a title.
    return [path for path in _TESTS.rglob("*.py") if path.stem != "_effect_title_omissions"]


@pytest.fixture(scope="module")
def unported(effect_files: dict[str, Path]) -> dict[str, list[str]]:
    """Each Effect file's titles that no pyfect test naming that file carries."""
    ports = read_ports(_test_modules(), effect_files)
    found: dict[str, list[str]] = defaultdict(list)
    for relative, path in effect_files.items():
        own = ports.get(relative, Ports())
        for title in titles_in_source(path.read_text()):
            if not is_ported(title, own) and not is_noted_as_omitted(title, own):
                found[relative].append(title)
    return found


def test_every_effect_title_is_ported_or_omitted_with_a_reason(
    unported: dict[str, list[str]],
) -> None:
    missing = sorted(
        {
            f"{path}: {title!r}"
            for path, titles in unported.items()
            for title in titles
            if reason_for(path, title) is None
        }
    )
    assert not missing, (
        f"{len(missing)} Effect titles are neither ported (a test's docstring, name or "
        "parametrized id carries the title) nor in tests/_effect_title_omissions.py:\n"
        + "\n".join(missing)
    )


def test_every_omission_still_omits_something(unported: dict[str, list[str]]) -> None:
    stale = [
        f"{omission.path} ({omission.titles.pattern if omission.titles else 'whole file'})"
        for omission in OMISSIONS
        if not any(
            fnmatch(path, omission.path)
            and (omission.titles is None or any(omission.titles.search(t) for t in titles))
            for path, titles in unported.items()
        )
    ]
    assert not stale, f"these omissions match no unported title, so remove them: {stale}"


def test_every_named_effect_file_is_one_file(effect_files: dict[str, Path]) -> None:
    """A test names the Effect file it ports by enough of its path to pick one file."""
    ambiguous = sorted(
        f"{path.relative_to(_TESTS)}: {mention}"
        for path in _test_modules()
        for doc in docstrings(path)
        for mention in ambiguous_mentions(doc, effect_files)
    )
    assert not ambiguous, (
        "these docstrings name several Effect files; write more of the path "
        f"(``sql-pg/test/Client.test.ts``): {ambiguous}"
    )


def test_every_omission_has_a_reason() -> None:
    assert all(omission.reason.strip() for omission in OMISSIONS)


def test_the_recorded_count_of_open_titles_is_the_lists(
    unported: dict[str, list[str]],
) -> None:
    """Counted per occurrence: a file can repeat a title under other ``describe`` blocks."""
    open_titles = sum(
        (reason_for(path, title) or "").startswith("NOT_PORTED")
        for path, titles in unported.items()
        for title in titles
    )
    parity = (_TESTS.parent / "docs" / "PARITY.md").read_text()
    assert f"{open_titles} titles NOT_PORTED, all open" in parity
