"""pyfect's stability bar: an area is stable once it has been clean for 7 days in a row.

Clean means: no "Fixed" entry touching the area merged to main (a changes/*.fixed.md fragment,
or CHANGELOG.md's), every CI run on main
green on its first attempt, the nightly soak (.github/workflows/soak-nightly.yml) green, and
no open item for the area in tests/stability_known_bugs.toml.

    python scripts/stability.py          # a summary per area
    python scripts/stability.py --json   # the report as JSON

It reads main's history of CHANGELOG.md and changes/ with git and the workflow runs with `gh api`.
"""

import argparse
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast, get_args

ROOT = Path(__file__).resolve().parent.parent
KNOWN_BUGS = ROOT / "tests" / "stability_known_bugs.toml"
SOAK_WORKFLOW = "soak-nightly.yml"
STABLE_DAYS = 7
RUN_WINDOW_DAYS = 14
"""How far back the workflow runs are read; a clean streak longer than this reads as this."""
SOAK_STALE = timedelta(hours=36)
"""A daily soak whose newest run is older than this has stopped running."""

type Area = Literal[
    "core", "cluster", "workflow", "sql", "http", "rpc", "ai", "platform", "observability"
]
AREAS: tuple[Area, ...] = get_args(Area.__value__)

_SOURCES: dict[Area, str] = {
    "cluster": r"cluster|shard|runner_storage|\bentit(?:y|ies)\b|singleton|message_storage",
    "workflow": r"\bworkflows?\b|\bactivit(?:y|ies)\b|durable|compensat",
    "sql": (
        r"\bsql|\bpg\b|postgres|mysql|mssql|sqlite|libsql|persist|event_?log|event_?journal"
        r"|key_value_store|migrat|asyncmy|psycopg|vitess"
    ),
    "http": (
        r"\bhttp|websocket|web_socket|hypercorn|uvicorn|\basgi\b|\brouter\b|find_?my_?way"
        r"|cookie|multipart|\bsse\b|live_server|static_server|abortsignal|abortcontroller"
    ),
    "rpc": r"\brpc|\bmcp\b|mcp_|ndjson|json-rpc",
    "ai": (
        r"\bai\b|\bai\.|language_?model|openai|anthropic|bedrock|openrouter|gemini"
        r"|\btool(?:kit)?s?\b|\bchat\b|embedding"
    ),
    "platform": (
        r"file_?system|\bsockets?\b|`process|process\.|child_?process|spawn|\bworkers?\b"
        r"|\bstdio\b|\bterminal\b|\bdns\b|descriptor"
    ),
    "observability": (
        r"otlp|otel|opentelemetry|\btrac(?:er|ing)\b|\bspans?\b|\bmetrics?\b"
        r"|\blog(?:ger|ging)\b|devtools|prometheus|error_reporter"
    ),
    "core": (
        r"\bfibers?\b|\bfx\.|schema|\bstreams?\b|\bchannel|\bqueue\b|pubsub|semaphore"
        r"|deferred|\blatch|\bscope\b|\blayers?\b|\bcause\b|duration|\bschedule|\bcache\b"
        r"|\btx_|transaction|hash_?(?:map|set)|\bdate_?time|config_?provider|pyfect\.testing"
        r"|@testing|test_?clock|blocking|interrupt|\bcli\b|\bcommand"
    ),
}
_PATTERNS: dict[Area, re.Pattern[str]] = {
    area: re.compile(source) for area, source in _SOURCES.items()
}


def areas_of(entry: str) -> frozenset[Area]:
    """The areas a CHANGELOG entry touches, from the modules and names it mentions; one that
    names none is core's."""
    text = entry.lower()
    found: frozenset[Area] = frozenset(
        area for area, pattern in _PATTERNS.items() if pattern.search(text)
    )
    return found or _CORE


_CORE: frozenset[Area] = frozenset({"core"})


def fixed_entries(changelog: str) -> list[str]:
    """Every entry under a ``### Fixed`` heading, each joined into one line."""
    entries: list[str] = []
    inside = False
    for line in changelog.splitlines():
        if line.startswith("#"):
            inside = line.strip() == "### Fixed"
        elif not inside:
            continue
        elif line.startswith("- "):
            entries.append(line[2:].strip())
        elif line.startswith(" ") and line.strip() and entries:
            entries[-1] += " " + line.strip()
    return entries


def _key(entry: str) -> str:
    """An entry's identity across commits: its start, so moving it from Unreleased to a release
    or rewording its end does not make it new."""
    return " ".join(entry.split())[:80]


def with_fragments(changelog: str, fragments: dict[str, str]) -> str:
    """CHANGELOG.md with the Fixed fragments of changes/ (name to body) as one more section,
    so a fix counts when it merges, not when it is released."""
    fixed = [body for name, body in sorted(fragments.items()) if name.endswith(".fixed.md")]
    return changelog + "\n## Fragments\n\n### Fixed\n\n" + "".join(fixed) if fixed else changelog


@dataclass(frozen=True)
class Snapshot:
    """CHANGELOG.md and its fragments as a commit on main left them."""

    sha: str
    merged_at: datetime
    text: str


@dataclass(frozen=True)
class FixedEntry:
    entry: str
    sha: str
    merged_at: datetime
    areas: frozenset[Area]


def added_fixed_entries(history: Sequence[Snapshot]) -> list[FixedEntry]:
    """The Fixed entries each commit added, ``history`` oldest first; an entry counts once, at
    the commit where it first appears."""
    seen: set[str] = set()
    added: list[FixedEntry] = []
    for snapshot in history:
        for entry in fixed_entries(snapshot.text):
            key = _key(entry)
            if key in seen:
                continue
            seen.add(key)
            added.append(FixedEntry(entry, snapshot.sha, snapshot.merged_at, areas_of(entry)))
    return added


@dataclass(frozen=True)
class Run:
    workflow: str
    conclusion: str | None
    attempt: int
    created_at: datetime
    url: str

    @property
    def finished(self) -> bool:
        return self.conclusion is not None

    @property
    def clean(self) -> bool:
        """Green on its first attempt (a skipped run is green: its conditions said not to run)."""
        return self.conclusion in ("success", "skipped") and self.attempt == 1


def parse_run(raw: dict[str, object]) -> Run:
    conclusion = raw.get("conclusion")
    attempt = raw.get("run_attempt", 1)
    return Run(
        workflow=str(raw.get("path") or raw.get("name")),
        conclusion=conclusion if isinstance(conclusion, str) else None,
        attempt=attempt if isinstance(attempt, int) else 1,
        created_at=_timestamp(str(raw["created_at"])),
        url=str(raw.get("html_url", "")),
    )


def _timestamp(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


@dataclass(frozen=True)
class KnownBug:
    area: Area
    title: str
    link: str


_AREA_NAMES: dict[str, Area] = {area: area for area in AREAS}


def parse_known_bugs(text: str) -> list[KnownBug]:
    """``[[bug]]`` tables with ``area``, ``title`` and ``link``; an unknown area or a missing
    field is an error here, not a silently uncounted bug."""
    raw = tomllib.loads(text).get("bug", [])
    if not isinstance(raw, list):
        raise ValueError("`bug` must be an array of tables ([[bug]])")
    bugs: list[KnownBug] = []
    for number, item in enumerate(cast("list[object]", raw), 1):
        if not isinstance(item, dict):
            raise ValueError(f"bug {number} is not a table")
        table = cast("dict[str, object]", item)
        fields = {key: table.get(key) for key in ("area", "title", "link")}
        missing = [key for key, value in fields.items() if not isinstance(value, str) or not value]
        if missing:
            raise ValueError(f"bug {number} lacks {', '.join(missing)}")
        area = _AREA_NAMES.get(str(fields["area"]))
        if area is None:
            raise ValueError(
                f"bug {number}: unknown area {fields['area']!r} (one of {', '.join(AREAS)})"
            )
        bugs.append(KnownBug(area, str(fields["title"]), str(fields["link"])))
    return bugs


@dataclass(frozen=True)
class Blocker:
    kind: Literal["fixed_entry", "ci_run", "soak", "known_bug"]
    detail: str
    at: datetime | None = None
    link: str = ""


@dataclass(frozen=True)
class AreaReport:
    area: Area
    days_clean: int
    stable: bool
    last_fixed: FixedEntry | None
    blockers: tuple[Blocker, ...]


def _days(since: datetime, now: datetime) -> int:
    return max(0, (now - since) // timedelta(days=1))


def _soak_state(runs: Sequence[Run], now: datetime) -> tuple[datetime, list[Blocker]]:
    """When the soak's clean streak began, and why it is not clean now."""
    finished = sorted((run for run in runs if run.finished), key=lambda run: run.created_at)
    if not finished:
        return now, [Blocker("soak", f"{SOAK_WORKFLOW} has no finished runs")]
    blockers: list[Blocker] = []
    bad = [run for run in finished if not run.clean]
    since = bad[-1].created_at if bad else finished[0].created_at
    window = now - timedelta(days=STABLE_DAYS)
    blockers += [
        Blocker("soak", f"{SOAK_WORKFLOW} {_run_state(run)}", run.created_at, run.url)
        for run in bad
        if run.created_at >= window
    ]
    if now - finished[-1].created_at > SOAK_STALE:
        blockers.append(
            Blocker("soak", f"{SOAK_WORKFLOW} has not run since", finished[-1].created_at)
        )
        since = now
    return since, blockers


def _run_state(run: Run) -> str:
    if run.attempt > 1:
        return f"was rerun (attempt {run.attempt}, {run.conclusion})"
    return str(run.conclusion)


def build_report(
    *,
    now: datetime,
    fixed: Sequence[FixedEntry],
    ci_runs: Sequence[Run],
    soak_runs: Sequence[Run],
    bugs: Sequence[KnownBug],
    run_window_start: datetime,
) -> list[AreaReport]:
    window = now - timedelta(days=STABLE_DAYS)
    bad_ci = sorted(
        (run for run in ci_runs if run.finished and not run.clean), key=lambda run: run.created_at
    )
    ci_since = bad_ci[-1].created_at if bad_ci else run_window_start
    ci_blockers = [
        Blocker("ci_run", f"{run.workflow} {_run_state(run)}", run.created_at, run.url)
        for run in bad_ci
        if run.created_at >= window
    ]
    soak_since, soak_blockers = _soak_state(soak_runs, now)
    reports: list[AreaReport] = []
    for area in AREAS:
        mine = [entry for entry in fixed if area in entry.areas]
        last = max(mine, key=lambda entry: entry.merged_at, default=None)
        area_bugs = [bug for bug in bugs if bug.area == area]
        starts = [ci_since, soak_since] + ([last.merged_at] if last else [])
        since = now if area_bugs else max(starts)
        blockers = (
            [
                Blocker("fixed_entry", entry.entry, entry.merged_at, entry.sha)
                for entry in mine
                if entry.merged_at >= window
            ]
            + ci_blockers
            + soak_blockers
            + [Blocker("known_bug", bug.title, None, bug.link) for bug in area_bugs]
        )
        days = _days(since, now)
        reports.append(
            AreaReport(area, days, days >= STABLE_DAYS and not blockers, last, tuple(blockers))
        )
    return reports


def to_json(reports: Iterable[AreaReport], now: datetime) -> dict[str, object]:
    def when(at: datetime | None) -> str | None:
        return at.isoformat() if at else None

    return {
        "generated_at": now.isoformat(),
        "stable_days": STABLE_DAYS,
        "areas": {
            report.area: {
                "days_clean": report.days_clean,
                "stable": report.stable,
                "last_fixed": None
                if report.last_fixed is None
                else {
                    "date": when(report.last_fixed.merged_at),
                    "sha": report.last_fixed.sha,
                    "entry": report.last_fixed.entry,
                },
                "blockers": [
                    {
                        "kind": blocker.kind,
                        "detail": blocker.detail,
                        "at": when(blocker.at),
                        "link": blocker.link,
                    }
                    for blocker in report.blockers
                ],
            }
            for report in reports
        },
    }


def summary(reports: Iterable[AreaReport]) -> str:
    lines: list[str] = []
    for report in reports:
        state = "stable" if report.stable else "not stable"
        lines.append(f"{report.area}: {state}, {report.days_clean} of {STABLE_DAYS} days clean")
        if report.last_fixed:
            entry = report.last_fixed.entry
            short = entry if len(entry) <= 100 else entry[:97] + "..."
            lines.append(f"  last fix {report.last_fixed.merged_at:%Y-%m-%d}: {short}")
        counts: dict[str, int] = {}
        for blocker in report.blockers:
            counts[blocker.kind] = counts.get(blocker.kind, 0) + 1
        if counts:
            listed = ", ".join(
                f"{count} {kind.replace('_', ' ')}" for kind, count in counts.items()
            )
            lines.append(f"  blockers: {listed}")
        lines.extend(
            f"    known bug: {blocker.detail} ({blocker.link})"
            for blocker in report.blockers
            if blocker.kind == "known_bug"
        )
    return "\n".join(lines)


def _run(*args: str) -> str:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True).stdout


def changelog_history(ref: str) -> list[Snapshot]:
    log = _run(
        "git", "log", "--first-parent", "--format=%H %cI", ref, "--", "CHANGELOG.md", "changes"
    )
    snapshots: list[Snapshot] = []
    for line in reversed(log.splitlines()):
        sha, date = line.split()
        names = _run("git", "ls-tree", "--name-only", f"{sha}:", "changes/").split()
        fragments = {
            name.removeprefix("changes/"): _run("git", "show", f"{sha}:{name}") for name in names
        }
        text = with_fragments(_run("git", "show", f"{sha}:CHANGELOG.md"), fragments)
        snapshots.append(Snapshot(sha, _timestamp(date), text))
    return snapshots


def _gh_runs(endpoint: str) -> list[Run]:
    jq = ".workflow_runs[] | {path, name, conclusion, run_attempt, created_at, html_url, event}"
    out = _run("gh", "api", "--paginate", endpoint, "--jq", jq)
    raws = [json.loads(line) for line in out.splitlines() if line]
    return [
        parse_run(raw) for raw in raws if raw.get("event") not in ("pull_request", "merge_group")
    ]


def main_runs(start: datetime, now: datetime) -> list[Run]:
    """Main's runs, one day per request (the API answers at most 1000 runs a query)."""
    runs: list[Run] = []
    day = start.date()
    while day <= now.date():
        runs += _gh_runs(
            f"repos/{{owner}}/{{repo}}/actions/runs?branch=main&created={day}&per_page=100"
        )
        day += timedelta(days=1)
    soak = f".github/workflows/{SOAK_WORKFLOW}"
    return [run for run in runs if run.workflow != soak]


def soak_runs() -> list[Run]:
    endpoint = (
        f"repos/{{owner}}/{{repo}}/actions/workflows/{SOAK_WORKFLOW}/runs?branch=main&per_page=100"
    )
    try:
        return _gh_runs(endpoint)
    except subprocess.CalledProcessError as error:
        if "Not Found" in (error.stderr or ""):
            return []
        raise


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="pyfect's stability bar, per area")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--ref", default="origin/main", help="main's ref (default origin/main)")
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    start = now - timedelta(days=RUN_WINDOW_DAYS)
    reports = build_report(
        now=now,
        fixed=added_fixed_entries(changelog_history(args.ref)),
        ci_runs=main_runs(start, now),
        soak_runs=soak_runs(),
        bugs=parse_known_bugs(KNOWN_BUGS.read_text(encoding="utf-8")),
        run_window_start=start,
    )
    print(json.dumps(to_json(reports, now), indent=2) if args.json else summary(reports))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
