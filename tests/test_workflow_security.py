"""The GitHub workflows keep the supply-chain rules of docs/security-review-2026-11.md.

Every third-party action is pinned to a full commit SHA (a tag can be moved to other code),
no workflow runs on `pull_request_target` (it hands a fork's code the base repository's
secrets), every workflow starts read-only, only the publishing job may mint an OIDC token, and
no `run:` script interpolates text a pull request author controls.
"""

import re
from pathlib import Path

WORKFLOWS = sorted((Path(__file__).resolve().parent.parent / ".github" / "workflows").glob("*.yml"))

# Text an outside contributor chooses: interpolated into a shell script it runs as code.
_ATTACKER_CONTEXTS = re.compile(
    r"\$\{\{\s*(github\.event\.(pull_request|issue|comment|review|head_commit|commits|pages)"
    r"|github\.head_ref)"
)


def test_there_are_workflows():
    assert {path.name for path in WORKFLOWS} >= {"ci.yml", "release.yml", "audit.yml"}


def test_every_action_is_pinned_to_a_commit():
    for path in WORKFLOWS:
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
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        found = _ATTACKER_CONTEXTS.search(text)
        assert found is None, f"{path.name} interpolates {found.group(0)}...; pass it via env"
