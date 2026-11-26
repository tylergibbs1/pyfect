"""Every ``it`` / ``test`` title in Effect's checkout is ported, or omitted with a reason.

A title counts as ported only by a test that names its Effect file. The checkout is the
``effect_checkout`` fixture's (``_effect_ref.py``): the tests that read it skip without one and
fail on a checkout of another commit than the one CI pins, which the lists are written against. See
``_effect_titles.py`` for what counts as ported and ``_effect_title_omissions.py`` for the list.
"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

import _effect_titles
import _parity_counts
import pytest
from _effect_title_omissions import OMISSIONS, open_title_count, reason_for
from _effect_titles import (
    ambiguous_mentions,
    docstrings,
)
from _parity_counts import PARITY
from _source import TESTS


@pytest.fixture(scope="module")
def effect_files(effect_checkout: Path) -> dict[str, Path]:
    return _effect_titles.effect_files_in(effect_checkout)


@pytest.fixture(scope="module")
def unported(effect_files: dict[str, Path]) -> dict[str, list[str]]:
    return _effect_titles.unported_titles(effect_files)


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
        f"{path.relative_to(TESTS)}: {mention}"
        for path in _effect_titles.porting_modules()
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
    stale = _parity_counts.rewrite(PARITY.read_text(), open_title_count(unported)).stale
    assert not stale, f"docs/PARITY.md: {stale}; run `{_parity_counts.WRITE}`"
