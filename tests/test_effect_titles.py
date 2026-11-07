"""Every ``it`` / ``test`` title in Effect's checkout is ported, or omitted with a reason.

Skipped without the checkout at ``../pyfect-ref/effect``, as in CI. See
``_effect_titles.py`` for what counts as ported and ``_effect_title_omissions.py`` for the list.
"""

from __future__ import annotations

from collections import defaultdict
from fnmatch import fnmatch
from pathlib import Path

import pytest
from _effect_title_omissions import OMISSIONS, reason_for
from _effect_titles import (
    effect_test_files,
    is_noted_as_omitted,
    is_ported,
    read_ports,
    titles_in_source,
)

_TESTS = Path(__file__).parent
_PACKAGES = _TESTS.parent.parent / "pyfect-ref" / "effect" / "packages"

pytestmark = pytest.mark.skipif(not _PACKAGES.is_dir(), reason=f"no Effect checkout at {_PACKAGES}")


@pytest.fixture(scope="module")
def unported() -> dict[str, list[str]]:
    """Each Effect file's titles that no pyfect test carries."""
    # The omission list's own patterns are strings too; they must not count as ports of a title.
    ports = read_ports(
        path for path in _TESTS.rglob("*.py") if path.stem != "_effect_title_omissions"
    )
    found: dict[str, list[str]] = defaultdict(list)
    for path in effect_test_files(_PACKAGES):
        relative = path.relative_to(_PACKAGES).as_posix()
        for title in titles_in_source(path.read_text()):
            if not is_ported(title, ports) and not is_noted_as_omitted(title, ports):
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
