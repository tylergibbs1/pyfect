"""scripts/stability.py measures the stability bar: per area, days since the last Fixed entry,
red or rerun CI run on main, failed nightly soak, or open known bug."""

import importlib.util
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("stability", ROOT / "scripts" / "stability.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["stability"] = module
    spec.loader.exec_module(module)
    return module


stability = _script()
NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)

CHANGELOG_V1 = """# Changelog

## Unreleased

### Added

- `pyfect.rational`: exact fractions.

### Fixed

- `hypercorn_server`: after a too-large WebSocket message the server sent the 1009 close
  and closed the connection.

- Cluster SQL runner storage (PostgreSQL, MySQL): a burst of shard releases timed out.

## 0.6.10 (2026-11-16)

### Fixed

- A `@testing.effect` test whose deadline passed reported nothing.

### Performance

- Hex decoding uses constant memory.
"""

CHANGELOG_V2 = """# Changelog

## Unreleased

### Fixed

- `Effect.tx` no longer spins when its body recovers `tx_retry`.

## 0.6.11 (2026-11-17)

### Added

- `pyfect.rational`: exact fractions.

### Fixed

- `hypercorn_server`: after a too-large WebSocket message the server sent the 1009 close
  and closed the connection, now after reading the client's close.

- Cluster SQL runner storage (PostgreSQL, MySQL): a burst of shard releases timed out.

## 0.6.10 (2026-11-16)

### Fixed

- A `@testing.effect` test whose deadline passed reported nothing.
"""


def test_fixed_entries_are_read_from_every_fixed_section_only():
    assert stability.fixed_entries(CHANGELOG_V1) == [
        (
            "`hypercorn_server`: after a too-large WebSocket message the server sent the 1009 "
            "close and closed the connection."
        ),
        "Cluster SQL runner storage (PostgreSQL, MySQL): a burst of shard releases timed out.",
        "A `@testing.effect` test whose deadline passed reported nothing.",
    ]


def test_an_entry_counts_once_where_it_first_appears():
    """Releasing moves entries out of Unreleased, and a later commit may reword an entry's end;
    neither is a new fix."""
    first = datetime(2026, 11, 16, tzinfo=UTC)
    second = datetime(2026, 11, 18, tzinfo=UTC)
    history = [
        stability.Snapshot("a" * 40, first, CHANGELOG_V1),
        stability.Snapshot("b" * 40, second, CHANGELOG_V2),
    ]
    added = stability.added_fixed_entries(history)
    assert [(entry.sha[0], entry.merged_at) for entry in added] == [
        ("a", first),
        ("a", first),
        ("a", first),
        ("b", second),
    ]
    assert added[-1].entry.startswith("`Effect.tx` no longer spins")


@pytest.mark.parametrize(
    ("entry", "areas"),
    [
        (
            "Cluster SQL runner storage (PostgreSQL, MySQL): a burst of shard releases timed out.",
            {"cluster", "sql"},
        ),
        ("`hypercorn_server`: the 1009 close came before the client's.", {"http"}),
        (
            "Cluster workflows: a transient `PersistenceError` while a workflow starts",
            {"cluster", "workflow", "sql"},
        ),
        ("Over workers, the RPC client and server collected transferables", {"rpc", "platform"}),
        (
            "`Toolkit.handle`: a stream stopped early dies with its tool handler's defects",
            {"ai", "core"},
        ),
        (
            "`socket.from_socket` registers its own duplicate of the adopted descriptor",
            {"platform"},
        ),
        ("`OtlpLogger` exported the no-op span's trace ids", {"observability"}),
        ("`Effect.tx` no longer spins when its body recovers `tx_retry`.", {"core"}),
        ("Hex decoding uses constant memory.", {"core"}),
        ("Ported tests no longer time out on slower CI runners.", {"core"}),
    ],
)
def test_an_entry_maps_to_the_areas_it_names(entry: str, areas: set[str]):
    assert stability.areas_of(entry) == areas


def _run(conclusion: str | None, days_ago: float, attempt: int = 1, workflow: str = "ci.yml"):
    return stability.Run(workflow, conclusion, attempt, NOW - timedelta(days=days_ago), "url")


def test_a_run_is_clean_only_green_on_its_first_attempt():
    assert _run("success", 1).clean
    assert _run("skipped", 1).clean
    assert not _run("success", 1, attempt=2).clean
    for conclusion in ("failure", "cancelled", "timed_out", "startup_failure"):
        assert not _run(conclusion, 1).clean
    assert not _run(None, 1).finished


def test_runs_parse_from_the_api_fields():
    run = stability.parse_run(
        {
            "path": ".github/workflows/ci.yml",
            "conclusion": "failure",
            "run_attempt": 2,
            "created_at": "2026-11-18T02:23:44Z",
            "html_url": "https://example.test/run",
        }
    )
    assert run == stability.Run(
        ".github/workflows/ci.yml",
        "failure",
        2,
        datetime(2026, 11, 18, 2, 23, 44, tzinfo=UTC),
        "https://example.test/run",
    )


def _report(
    *,
    fixed: list[tuple[str, float]] | None = None,
    ci: list[Any] | None = None,
    soak: list[Any] | None = None,
    bugs: str = "",
) -> dict[str, Any]:
    entries = [
        stability.FixedEntry(text, "c" * 40, NOW - timedelta(days=days), stability.areas_of(text))
        for text, days in fixed or []
    ]
    reports = stability.build_report(
        now=NOW,
        fixed=entries,
        ci_runs=[_run("success", day) for day in range(14)] if ci is None else ci,
        soak_runs=[_run("success", day, workflow="soak") for day in range(14)]
        if soak is None
        else soak,
        bugs=stability.parse_known_bugs(bugs),
        run_window_start=NOW - timedelta(days=14),
    )
    return {report.area: report for report in reports}


def test_an_area_clean_for_seven_days_is_stable():
    reports = _report(fixed=[("`hypercorn_server`: a fix.", 9)])
    assert reports["http"].days_clean == 9 and reports["http"].stable
    assert reports["http"].last_fixed.entry == "`hypercorn_server`: a fix."
    assert reports["rpc"].stable and reports["rpc"].last_fixed is None


def test_a_recent_fixed_entry_restarts_its_areas_count():
    reports = _report(fixed=[("Cluster shard releases timed out.", 3)])
    assert reports["cluster"].days_clean == 3 and not reports["cluster"].stable
    assert [blocker.kind for blocker in reports["cluster"].blockers] == ["fixed_entry"]
    assert reports["http"].stable


def test_a_red_or_rerun_run_on_main_restarts_every_area():
    ci = [_run("success", day) for day in range(14)]
    for runs in ([_run("failure", 2)], [_run("success", 2, attempt=2)]):
        reports = _report(ci=ci + runs)
        assert {report.days_clean for report in reports.values()} == {2}
        assert all(not report.stable for report in reports.values())
    old = _report(ci=[*ci, _run("failure", 10)])
    assert old["core"].days_clean == 10 and old["core"].stable


def test_the_soak_must_have_run_green_and_lately():
    missing = _report(soak=[])
    assert missing["core"].days_clean == 0
    assert [blocker.kind for blocker in missing["core"].blockers] == ["soak"]
    young = _report(soak=[_run("success", day, workflow="soak") for day in range(4)])
    assert young["core"].days_clean == 3 and not young["core"].stable
    stale = _report(soak=[_run("success", day, workflow="soak") for day in range(3, 14)])
    assert stale["core"].days_clean == 0 and not stale["core"].stable
    red = _report(
        soak=[*(_run("success", d, workflow="soak") for d in range(14)), _run("failure", 1)]
    )
    assert red["cluster"].days_clean == 1


def test_an_open_known_bug_blocks_its_area():
    reports = _report(bugs='[[bug]]\narea = "rpc"\ntitle = "stalls"\nlink = "https://x.test/1"\n')
    assert reports["rpc"].days_clean == 0 and not reports["rpc"].stable
    assert reports["rpc"].blockers[0].link == "https://x.test/1"
    assert reports["ai"].stable


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[[bug]]\narea = "ui"\ntitle = "t"\nlink = "l"\n', "unknown area 'ui'"),
        ('[[bug]]\narea = "rpc"\ntitle = "t"\n', "lacks link"),
        ('[[bug]]\narea = "rpc"\ntitle = ""\nlink = "l"\n', "lacks title"),
        ('bug = "rpc"\n', "array of tables"),
    ],
)
def test_a_malformed_known_bug_is_an_error(text: str, message: str):
    with pytest.raises(ValueError, match=re.escape(message)):
        stability.parse_known_bugs(text)


def test_the_checked_in_known_bugs_parse_with_links():
    bugs = stability.parse_known_bugs(stability.KNOWN_BUGS.read_text(encoding="utf-8"))
    assert bugs
    assert all(bug.link.startswith("https://github.com/") for bug in bugs)
    assert len({bug.link for bug in bugs}) == len(bugs), "one entry per bug"


def test_the_soak_the_report_reads_is_the_nightly_workflow():
    workflow = ROOT / ".github" / "workflows" / stability.SOAK_WORKFLOW
    assert re.search(r'(?m)^    - cron: "\d+ \d+ \* \* \*"$', workflow.read_text(encoding="utf-8"))


def test_the_summary_and_json_name_every_area():
    reports = list(_report(fixed=[("Cluster shard releases timed out.", 3)]).values())
    text = stability.summary(reports)
    assert all(f"{area}:" in text for area in stability.AREAS)
    assert "cluster: not stable, 3 of 7 days clean" in text
    data = stability.to_json(reports, NOW)
    areas = data["areas"]
    assert set(areas) == set(stability.AREAS)
