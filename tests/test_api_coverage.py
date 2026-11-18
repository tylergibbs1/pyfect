"""The coverage tables in docs/coverage/ match what ``scripts/api_coverage.py``
computes now: an export that loses its pyfect counterpart, a stale rename or
a §4 key that no longer exists fails here. Reads Effect's source from the
``effect_checkout`` fixture."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CLUSTERS = sorted(p.stem for p in (ROOT / "docs" / "coverage").glob("*.md"))


@pytest.mark.usefixtures("effect_checkout")
@pytest.mark.parametrize("cluster", CLUSTERS)
def test_saved_coverage_table_is_current(cluster: str) -> None:
    run = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "api_coverage.py"), cluster, "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stderr


@pytest.mark.parametrize("cluster", ["core-a", "core-b", "config-data"])
def test_cluster_has_no_missing_exports(cluster: str) -> None:
    table = (ROOT / "docs" / "coverage" / f"{cluster}.md").read_text()
    assert "| missing |" not in table
