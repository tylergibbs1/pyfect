"""The GitHub workflows keep the supply-chain rules of docs/security-review-2026-11.md.

Every third-party action is pinned to a full commit SHA (a tag can be moved to other code),
no workflow runs on `pull_request_target` (it hands a fork's code the base repository's
secrets), every workflow starts read-only, only the publishing job may mint an OIDC token, and
no `run:` script interpolates text a pull request author controls.
"""

import re
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from pyfect.encoding import yaml

GITHUB = Path(__file__).resolve().parent.parent / ".github"
WORKFLOWS = sorted((GITHUB / "workflows").glob("*.yml"))
# Composite actions the workflows use (`uses: ./.github/actions/...`): their steps run in the
# workflow's job, so they keep the same rules.
ACTIONS = sorted((GITHUB / "actions").glob("*/action.yml"))

# Text an outside contributor chooses: interpolated into a shell script it runs as code.
_ATTACKER_CONTEXTS = re.compile(
    r"\$\{\{\s*(github\.event\.(pull_request|issue|comment|review|head_commit|commits|pages)"
    r"|github\.head_ref)"
)


def test_there_are_workflows():
    assert {path.name for path in WORKFLOWS} >= {"ci.yml", "release.yml", "audit.yml"}
    assert {path.parent.name for path in ACTIONS} >= {"check-setup"}


def test_every_action_is_pinned_to_a_commit():
    for path in [*WORKFLOWS, *ACTIONS]:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"\s*(?:-\s+)?uses:\s*(\S+)", line)
            if match is None or match.group(1).startswith("./"):
                continue
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", match.group(1)), (
                f"{path.name}: {line.strip()} is not pinned to a commit SHA"
            )


def test_no_workflow_runs_on_pull_request_target():
    for path in WORKFLOWS:
        assert "pull_request_target" not in path.read_text(encoding="utf-8"), path.name


def test_every_workflow_starts_read_only():
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        assert re.search(r"(?m)^permissions:\n  contents: read\n(?!  )", text), (
            f"{path.name} must declare top-level `permissions: contents: read` and nothing more"
        )


def test_only_the_publish_job_mints_an_oidc_token():
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        count = text.count("id-token: write")
        if path.name == "release.yml":
            publish = text.split("\n  publish:\n", 1)
            assert count == 1 and len(publish) == 2 and "id-token: write" in publish[1]
        else:
            assert count == 0, f"{path.name} asks for an OIDC token"


def test_no_script_interpolates_pull_request_text():
    for path in [*WORKFLOWS, *ACTIONS]:
        text = path.read_text(encoding="utf-8")
        found = _ATTACKER_CONTEXTS.search(text)
        assert found is None, f"{path.name} interpolates {found.group(0)}...; pass it via env"


# A called workflow's token can only keep or lower its caller's permissions, never raise them,
# so a reusable workflow whose job asks for more than its caller grants never starts
# (`startup_failure`, no jobs, no logs). 0.6.13's release did that: ci.yml's check job asked for
# `actions: read` and release.yml granted only `contents: read`.
_LEVELS = {"none": 0, "read": 1, "write": 2}
_NAMES = {level: name for name, level in _LEVELS.items()}


def _mapping(value: object, where: str) -> dict[str, object]:
    assert isinstance(value, dict), f"{where} is not a mapping"
    return {str(key): item for key, item in cast("dict[object, object]", value).items()}


def _permissions(value: object, where: str) -> dict[str, int]:
    """A `permissions:` mapping as scope -> level; a scope it leaves out is `none`."""
    return {scope: _LEVELS[str(level)] for scope, level in _mapping(value, where).items()}


def _asks_for_more(granted: dict[str, int], called: Mapping[str, object], name: str) -> list[str]:
    """Each scope a job of the called workflow asks for at a higher level than the caller grants."""
    top = called.get("permissions", {})
    found: list[str] = []
    for job_id, job in _mapping(called.get("jobs"), f"{name} jobs").items():
        asked = _permissions(_mapping(job, job_id).get("permissions", top), f"{name} {job_id}")
        found += [
            f"{name} job {job_id} asks for {scope}: {_NAMES[level]}"
            for scope, level in sorted(asked.items())
            if level > granted.get(scope, 0)
        ]
    return found


def _workflow(name: str) -> dict[str, object]:
    return _mapping(yaml.parse((GITHUB / "workflows" / name).read_text(encoding="utf-8")), name)


def test_every_reusable_workflow_call_grants_what_the_called_workflow_asks_for():
    calls = 0
    for path in WORKFLOWS:
        caller = _workflow(path.name)
        for job_id, job in _mapping(caller.get("jobs"), f"{path.name} jobs").items():
            uses = _mapping(job, job_id).get("uses")
            if not (isinstance(uses, str) and uses.startswith("./.github/workflows/")):
                continue
            calls += 1
            where = f"{path.name} job {job_id}"
            assert "permissions" in caller or "permissions" in _mapping(job, job_id), where
            granted = _permissions(
                _mapping(job, job_id).get("permissions", caller["permissions"]), where
            )
            called = uses.removeprefix("./.github/workflows/")
            assert _asks_for_more(granted, _workflow(called), called) == [], (
                f"{where} calls {called} without granting what it asks for; give the job a "
                "`permissions:` block covering it"
            )
    assert calls >= 3, "release.yml calls ci.yml, extras.yml and docs.yml"


def test_the_permission_check_rejects_a_call_that_grants_too_little():
    called = {
        "permissions": {"contents": "read"},
        "jobs": {"test": {}, "check": {"permissions": {"contents": "read", "actions": "read"}}},
    }
    assert _asks_for_more({"contents": 1}, called, "ci.yml") == [
        "ci.yml job check asks for actions: read"
    ]
    assert _asks_for_more({"contents": 1, "actions": 1}, called, "ci.yml") == []
    assert _asks_for_more({"contents": 1, "actions": 2}, called, "ci.yml") == []
