"""``date_time.intl`` answers as Effect's ``DateTime.format``, ``formatUtc``
and ``formatLocal`` do under Node (``Intl.DateTimeFormat`` on ICU).

``intl_answers.json`` is what ``intl_oracle.ts`` (Effect 4.1.2 under Node
24.22.1, ICU 78.3, CLDR 48) answers for every case of ``intl_matrix.py``;
regenerate it with ``scripts/gen_intl_answers.py`` after changing the matrix,
and regenerate the data (``scripts/gen_intl_cldr.py``) with the same Node.
Every case must match except the named ``KNOWN_DIFFERENCES``, each of which
must still differ, so the list cannot go stale.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from pyfect.date_time import intl, zone_named

from .intl_matrix import (
    ANSWERS,
    ENVIRONMENT,
    NODE_LOCALES,
    ORACLE,
    UNSUPPORTED_CALENDAR_LOCALES,
    Case,
    cases,
    digest,
)

_ROOT = Path(__file__).parent.parent.parent

_KEYS = {"dateStyle": "date_style", "timeStyle": "time_style", "timeZone": "time_zone"}
_UNSUPPORTED = re.compile(r"the [a-z-]+ calendar is not supported")


def _is_unsupported_calendar(case: Case, ours: str, _node: str) -> bool:
    return case[3].get("locale") in UNSUPPORTED_CALENDAR_LOCALES and bool(_UNSUPPORTED.search(ours))


KNOWN_DIFFERENCES: dict[str, Callable[[Case, str, str], bool]] = {
    # Only the Gregorian, Buddhist and Persian calendars are ported; a -u-ca-
    # naming another is a ValueError where Intl formats in it.
    "calendar not ported": _is_unsupported_calendar,
}


@dataclass(frozen=True)
class _Recorded:
    versions: tuple[str, str, str, str]
    """Node's, ICU's, CLDR's and tz's."""
    cases: str
    answers: list[str]


def _recorded() -> _Recorded:
    data = cast("dict[str, str]", json.loads(ANSWERS.read_text(encoding="utf-8")))
    answers = cast("list[str]", data["answers"])
    versions = (data["node"], data["icu"], data["cldr"], data["tz"])
    return _Recorded(versions, data["cases"], answers)


def _ours(case: Case) -> str:
    function, millis, zone_id, options = case
    keyword = {_KEYS.get(key, key): value for key, value in options.items()}
    instant = datetime.fromtimestamp(millis / 1000, UTC)
    try:
        if function == "format":
            zone = zone_named(zone_id)
            assert zone is not None, zone_id
            return intl.format(instant.astimezone(zone), **keyword)  # pyright: ignore[reportArgumentType]
        run = intl.format_utc if function == "formatUtc" else intl.format_local
        return run(instant, **keyword)  # pyright: ignore[reportArgumentType]
    except (TypeError, ValueError) as error:
        name = "TypeError" if isinstance(error, TypeError) else "RangeError"
        return f"!{name}: {error}"


@pytest.fixture
def node_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The environment the answers were recorded in (the default locale)."""
    for name in ("LC_ALL", "LC_MESSAGES", "LANG", "TZ"):
        monkeypatch.delenv(name, raising=False)
    for name, value in ENVIRONMENT.items():
        monkeypatch.setenv(name, value)


def test_the_answers_cover_the_matrix() -> None:
    assert _recorded().cases == digest(cases()), (
        "the matrix changed: regenerate intl_answers.json (scripts/gen_intl_answers.py)"
    )


def test_the_data_is_from_the_answers_node() -> None:
    from pyfect.date_time._intl._data import meta

    data = meta()
    assert (data.node, data.icu, data.cldr, data.tz) == _recorded().versions, (
        "regenerate cldr.zip and intl_answers.json with the same Node"
    )
    assert sorted(data.available) == list(NODE_LOCALES)


@pytest.mark.usefixtures("node_environment")
def test_formats_as_node() -> None:
    answers = _recorded().answers
    unexplained: list[tuple[Case, str, str]] = []
    explained: dict[str, int] = dict.fromkeys(KNOWN_DIFFERENCES, 0)
    for case, node in zip(cases(), answers, strict=True):
        ours = _ours(case)
        if ours == node:
            continue
        name = next((n for n, test in KNOWN_DIFFERENCES.items() if test(case, ours, node)), None)
        if name is None:
            unexplained.append((case, ours, node))
        else:
            explained[name] += 1
    assert not unexplained, f"{len(unexplained)} differ from Node: {unexplained[:5]}"
    assert all(explained.values()), f"a known difference no longer occurs: {explained}"


def test_the_docs_state_the_versions() -> None:
    from pyfect.date_time._intl._data import meta

    page = (_ROOT / "website" / "content" / "docs" / "schedules.mdx").read_text("utf-8")
    data = meta()
    for version in (f"CLDR {data.cldr}", f"ICU {data.icu}", f"Node {data.node}"):
        assert version in page
    for name in KNOWN_DIFFERENCES:
        assert name in page


@pytest.mark.skipif(
    shutil.which("node") is None or "PYFECT_EFFECT_REF" not in os.environ,
    reason="needs node and an Effect checkout (PYFECT_EFFECT_REF)",
)
def test_the_answers_are_nodes_answers() -> None:
    node = subprocess.run(["node", "--version"], capture_output=True, text=True, check=True)
    recorded = _recorded()
    if node.stdout.strip() != f"v{recorded.versions[0]}":
        pytest.skip(f"answers are from Node {recorded.versions[0]}, this is {node.stdout.strip()}")
    sample = cases()[::50]
    result = subprocess.run(
        ["node", str(ORACLE)],
        input=json.dumps(sample),
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, **ENVIRONMENT},
    )
    assert json.loads(result.stdout)["answers"] == recorded.answers[::50]


def test_a_zone_read_from_a_file_without_a_name_formats_with_its_offset() -> None:
    # zone_local falls back to ZoneInfo.from_file(/etc/localtime), whose key is
    # None; Intl then has only the offset to name it by.
    tzif = Path("/usr/share/zoneinfo/Asia/Tokyo")
    if not tzif.exists():
        pytest.skip("no system zoneinfo")
    with tzif.open("rb") as file:
        zone = ZoneInfo.from_file(file)
    moment = datetime(2024, 3, 15, 12, 4, 6, tzinfo=UTC).astimezone(zone)
    assert intl.format(moment, locale="en-US", time_style="long") == "9:04:06 PM GMT+9"
