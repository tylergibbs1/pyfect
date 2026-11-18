"""``_effect_ref.py``: tests and scripts read Effect only from a checkout at the commit CI pins.

A guard that read a checkout of another Effect (or found none in a worktree and skipped) passed
locally and failed in CI, or the other way round; now a checkout at another commit fails,
naming both commits, and nothing else locates one."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import _effect_ref
import _source
import pytest
from _source import ROOT, TESTS


def _git(path: Path, *args: str) -> str:
    identity = ("-c", "user.name=t", "-c", "user.email=t@example.com")
    run = subprocess.run(
        ["git", "-C", str(path), *identity, *args], check=True, capture_output=True, text=True
    )
    return run.stdout.strip()


def _effect(path: Path) -> list[str]:
    """A repository with ``packages/`` and two commits, oldest first."""
    (path / "packages").mkdir(parents=True)
    _git(path, "init", "-q")
    commits: list[str] = []
    for version in ("4.1.2", "4.1.4"):
        (path / "packages" / "version").write_text(version)
        _git(path, "add", ".")
        _git(path, "commit", "-qm", version)
        commits.append(_git(path, "rev-parse", "HEAD"))
    return commits


def test_a_checkout_at_the_pin_is_returned(tmp_path: Path) -> None:
    shared = tmp_path / "effect"
    _, pin = _effect(shared)
    assert _effect_ref.checkout(pin, environ={}, shared=shared) == shared


def test_a_checkout_at_another_commit_fails_naming_both_and_the_fix(tmp_path: Path) -> None:
    shared = tmp_path / "effect"
    old, pin = _effect(shared)
    _git(shared, "checkout", "-q", "--detach", old)
    with pytest.raises(_effect_ref.WrongCommit) as wrong:
        _effect_ref.checkout(pin, environ={}, shared=shared)
    message = str(wrong.value)
    assert f"{shared} is at {old}" in message
    assert f"EFFECT_COMMIT {pin}" in message
    assert f"git -C {shared} fetch {_effect_ref.UPSTREAM} {pin}" in message
    assert "uv run python tests/_effect_ref.py" in message


def test_a_directory_that_is_no_git_checkout_is_at_no_commit(tmp_path: Path) -> None:
    (tmp_path / "effect" / "packages").mkdir(parents=True)
    with pytest.raises(_effect_ref.WrongCommit, match="is at no git commit"):
        _effect_ref.checkout("a" * 40, environ={}, shared=tmp_path / "effect")


def test_no_checkout_is_its_own_error(tmp_path: Path) -> None:
    with pytest.raises(_effect_ref.NoCheckout, match="no Effect checkout"):
        _effect_ref.checkout("a" * 40, environ={}, shared=tmp_path / "effect")


def test_the_variable_wins_then_the_pins_own_checkout_then_the_shared_one(
    tmp_path: Path,
) -> None:
    shared = tmp_path / "effect"
    pin = "0123456789ab" + "c" * 28
    assert _effect_ref.location(pin, {}, shared) == shared
    own = _effect_ref.own_location(pin, shared)
    assert own == tmp_path / "effect-0123456789ab"
    own.mkdir()
    assert _effect_ref.location(pin, {}, shared) == own
    named = {_effect_ref.ENV: str(tmp_path / "elsewhere")}
    assert _effect_ref.location(pin, named, shared) == tmp_path / "elsewhere"


def test_main_makes_the_pins_own_checkout_beside_a_shared_one_at_another_commit(
    tmp_path: Path,
) -> None:
    """Worktrees on branches pinning different Effects don't fight over the shared checkout."""
    shared = tmp_path / "effect"
    old, pin = _effect(shared)
    _git(shared, "checkout", "-q", "--detach", old)
    made = _effect_ref.main(pin, {}, shared)
    assert made == _effect_ref.own_location(pin, shared)
    assert _effect_ref.head(made) == pin
    assert _effect_ref.head(shared) == old
    assert _effect_ref.checkout(pin, environ={}, shared=shared) == made
    assert _effect_ref.main(pin, {}, shared) == made


def test_make_clones_a_missing_shared_checkout_first(tmp_path: Path) -> None:
    upstream = tmp_path / "upstream"
    _, pin = _effect(upstream)
    shared = tmp_path / "effect"
    made = _effect_ref.make(pin, shared, upstream=str(upstream))
    assert made == _effect_ref.own_location(pin, shared)
    assert _effect_ref.head(made) == pin
    assert (shared / ".git").is_dir()


def test_the_pin_is_ci_s_one_effect_commit(tmp_path: Path) -> None:
    pin = _effect_ref.pinned_commit()
    assert re.fullmatch(r"[0-9a-f]{40}", pin)
    assert f"EFFECT_COMMIT: {pin}" in (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    two = tmp_path / "ci.yml"
    two.write_text(f"EFFECT_COMMIT: {'a' * 40}\nEFFECT_COMMIT: {'b' * 40}\n")
    with pytest.raises(ValueError, match="not one EFFECT_COMMIT"):
        _effect_ref.pinned_commit(two)


_LOCATORS = ("pyfect-ref", "PYFECT_" + "REF")


def test_only_effect_ref_locates_the_checkout() -> None:
    """Python finds the checkout through ``_effect_ref`` (``checkout()`` or the
    ``effect_checkout`` fixture), never by path or by reading the variable itself; the Node
    oracles read only the variable, which the Python that runs them sets."""
    own = {TESTS / "_effect_ref.py", TESTS / "test_effect_ref.py"}
    python = [
        *_source.files(TESTS),
        *_source.files(ROOT / "scripts"),
    ]
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in python
        if path not in own
        and (
            any(locator in _source.text(path) for locator in _LOCATORS)
            or '"' + _effect_ref.ENV + '"' in _source.text(path)
        )
    ]
    node = _source.files(TESTS, "*.ts")
    offenders += [
        path.relative_to(ROOT).as_posix()
        for path in node
        if any(locator in _source.text(path) for locator in _LOCATORS)
    ]
    assert offenders == []
    assert node, "no Node oracles found"
