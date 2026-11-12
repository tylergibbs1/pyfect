"""The weekly mutation run (scripts/mutation.py, .github/workflows/mutation.yml) stays runnable.

It runs only on a schedule, so a renamed test file or module would break it unseen until the
next Monday; these checks break the commit instead.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mutation", ROOT / "scripts" / "mutation.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["mutation"] = module  # dataclasses look their module up while building
    spec.loader.exec_module(module)
    return module


def test_every_group_names_existing_modules_and_tests():
    mutation = _script()
    for name, group in mutation.GROUPS.items():
        for source in group.sources:
            assert (ROOT / "src" / "pyfect" / source).is_file(), f"{name}: no module {source}"
        assert mutation._test_paths(group), name
        for test in group.deselect:
            path, _, title = test.partition("::")
            assert re.search(
                rf"def {re.escape(title.split('[')[0])}\(", (ROOT / "tests" / path).read_text()
            ), test


def test_the_baseline_scores_every_mutated_module():
    mutation = _script()
    modules = {
        "pyfect." + source.removesuffix(".py").replace("/", ".")
        for group in mutation.GROUPS.values()
        for source in group.sources
    }
    assert set(json.loads(mutation.BASELINE.read_text())) == modules


def test_the_workflow_is_on_demand_and_weekly_never_on_push():
    workflow = (ROOT / ".github" / "workflows" / "mutation.yml").read_text(encoding="utf-8")
    trigger = workflow.split("\njobs:")[0]
    assert "workflow_dispatch:" in trigger
    assert "schedule:" in trigger
    assert "push" not in trigger and "pull_request" not in trigger
    assert "scripts/mutation.py check ${{ matrix.group }}" in workflow
    matrix = re.search(r"(?m)^\s+group: \[(.*)\]$", workflow)
    assert matrix, "mutation.yml has no group matrix"
    assert [g.strip() for g in matrix.group(1).split(",")] == list(_script().GROUPS)
