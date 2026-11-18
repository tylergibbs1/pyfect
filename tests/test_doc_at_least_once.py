"""No doc or docstring claims that workflow activities or compensations run once.

They run at least once: a runner that loses a shard (a kill, or a lock refresh that times
out under load, as in Effect) drops its in-flight runs, and the replay on the shard's owner
runs again every activity whose result was not stored yet. 0.6.12's docs said "Compensations
run once" and "it runs once"; the dogfood cluster saw an activity run 12 times.

A paragraph (of Markdown, or of a Python docstring) that mentions activities, compensations
or workflow steps must not say "run once" or "runs once"."""

import ast
import re
from pathlib import Path

import _source

ROOT = _source.ROOT
# PARITY.md and CHANGELOG.md record history; they quote old claims on purpose.
DOCUMENTS = [
    ROOT / "README.md",
    *(p for p in (ROOT / "docs").glob("*.md") if p.name != "PARITY.md"),
    *(ROOT / "website" / "content").rglob("*.mdx"),
]

_ONCE = re.compile(r"\bruns? once\b", re.IGNORECASE)
_SUBJECT = re.compile(r"\b(activit(y|ies)|compensations?|steps?)\b", re.IGNORECASE)
_WORKFLOW = re.compile(r"\b(workflows?|durable)\b", re.IGNORECASE)


def _claims(text: str) -> list[str]:
    found: list[str] = []
    # Paragraphs, and each item of a list on its own.
    for paragraph in re.split(r"\n\s*\n|\n(?=\s*[-*] )", text):
        if not _ONCE.search(paragraph):
            continue
        subject = _SUBJECT.search(paragraph)
        if subject is None:
            continue
        # "step" alone is too common (schedules, execution plans): only in a workflow context.
        if subject.group(1).lower().startswith("step") and not _WORKFLOW.search(paragraph):
            continue
        found.append(" ".join(paragraph.split())[:200])
    return found


def _docstrings(path: Path) -> list[str]:
    nodes = _source.walk(path)
    out: list[str] = []
    for node in nodes:
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=True)
            if doc:
                out.append(doc)
    return out


def test_no_doc_says_activities_or_compensations_run_once() -> None:
    bad = [f"{p.relative_to(ROOT)}: {c}" for p in DOCUMENTS for c in _claims(_source.text(p))]
    assert not bad, "activities and compensations run at least once:\n" + "\n".join(bad)


def test_no_docstring_says_activities_or_compensations_run_once() -> None:
    bad = [
        f"{p.relative_to(ROOT)}: {c}"
        for p in _source.files(_source.SRC)
        if _source.may_hold(p, "once")
        for doc in _docstrings(p)
        for c in _claims(doc)
    ]
    assert not bad, "activities and compensations run at least once:\n" + "\n".join(bad)


def test_the_check_catches_the_old_claims() -> None:
    assert _claims("Compensations run once, in reverse order, after the failure.")
    assert _claims("An activity is an effect.\nRun inside a workflow, it runs once: its exit")
    assert _claims("durable steps that run once and replay, with durable sleeps")
    assert not _claims("Without ``attempts`` the step runs once.")
    assert not _claims("Activities run at least once.")
    assert not _claims("- Cron: jobs that run once per cluster.\n- Workflows: activities replay.")
