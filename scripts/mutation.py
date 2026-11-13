"""Mutation testing of pyfect's core: ``uv run python scripts/mutation.py run|report|check``.

mutmut (3.x) changes one thing at a time in the core modules below (a ``<`` becomes ``<=``, a
``True`` becomes ``False``, a call loses an argument) and runs the tests that reach the changed
function. A test that fails "kills" the mutant; a mutant every test passes with "survives",
and is either a gap in the tests or a change that cannot alter behaviour (an equivalent
mutant, skipped in the source with ``# pragma: no mutate, <why it is equivalent>``).

Each group mutates a few modules against the test files that exercise them, in its own
work directory (``.mutation/<group>``, git-ignored) so groups keep separate results and a
rerun only tests what changed. Within a group mutmut maps every function to the tests that
call it, so a mutant runs only those.

- ``run [GROUP...]``: mutate and test (every group by default); ``--max-children N``;
  ``--survivors`` tests only the surviving mutants again, after adding tests.
- ``report [GROUP...]``: the score of every module and its surviving mutants; ``--diffs``
  shows each survivor's change (``mutmut show NAME`` in ``.mutation/<group>`` shows one).
- ``check [GROUP...]``: fail when a module's score is below ``scripts/mutation_baseline.json``;
  ``--update`` records the current scores there instead.

The score is ``killed / (mutants - skipped)``: a timeout counts as killed, a mutant no test
reaches counts as survived.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / ".mutation"
BASELINE = ROOT / "scripts" / "mutation_baseline.json"
PYRIGHT = Path(sys.executable).parent / "pyright"


@dataclass(frozen=True, slots=True)
class Group:
    sources: tuple[str, ...]
    """Modules to mutate, relative to ``src/pyfect``."""
    tests: tuple[str, ...]
    """Test files (or globs) relative to ``tests``."""
    deselect: tuple[str, ...] = ()
    """Tests that read the source itself (its names, its AST), which mutmut rewrites, that
    need the stack depth its trampolines take, or that read process-wide state mutmut's
    repeated in-process runs leave changed."""


_RUNTIME_TESTS = (
    "test_fibers.py",
    "test_core.py",
    "test_primitives.py",
    "test_decided_results.py",
    "test_interrupt_delivery.py",
    "test_fiber_wait_release.py",
    "test_race_interruption.py",
    "test_for_each_interruption.py",
    "test_released_handoffs.py",
    "test_user_callbacks.py",
    "test_concurrency.py",
    "test_deferred.py",
    "test_effect_core_a.py",
    "test_queue.py",
    "test_queue_fairness.py",
    "test_generator_bodies.py",
    "test_run_functions.py",
    "test_fresh_stack_limit.py",
    "test_closed_owner_interrupts.py",
    "test_runtime_*.py",
    "interleave/test_*.py",
    "oracle/test_fiber*.py",
    "oracle/test_effect_*.py",
    "oracle/test_synchronous_resume.py",
    "oracle/test_deferred.py",
    "oracle/test_queue.py",
    "oracle/test_semaphore.py",
    "oracle/test_latch.py",
    "oracle/test_scheduler.py",
    "oracle/test_max_ops_interleaving.py",
    "oracle/test_custom_dispatchers.py",
    "test_scheduler_references.py",
    "test_tracing.py",
    "oracle/test_context_vars_resume.py",
)

_SCHEMA_TESTS = (
    "test_schema_*.py",
    "oracle/test_schema.py",
    "oracle/test_schema_ast*.py",
    "oracle/test_schema_compiler_api.py",
    "oracle/test_schema_checks.py",
    "oracle/test_schema_class.py",
    "oracle/test_schema_codecs.py",
    "oracle/test_schema_composites.py",
    "oracle/test_schema_constructor_default.py",
    "oracle/test_schema_errors.py",
    "oracle/test_schema_filter_groups.py",
    "oracle/test_schema_getter.py",
    "oracle/test_schema_issue*.py",
    "oracle/test_schema_leftovers.py",
    "oracle/test_schema_middleware.py",
    "oracle/test_schema_object_*.py",
    "oracle/test_schema_parser.py",
    "oracle/test_schema_recursion_depth.py",
    "oracle/test_schema_struct*.py",
    "oracle/test_schema_tagged.py",
    "oracle/test_schema_template_literal.py",
    "oracle/test_schema_transform.py",
)
# A mutated function runs behind a trampoline, so the 5000-deep values outgrow the stack.
_SCHEMA_DESELECT = tuple(
    f"oracle/test_schema_recursion_depth.py::{test}[5000]"
    for test in (
        "test_a_suspended_struct_decodes_a_deep_value",
        "test_a_suspended_struct_encodes_a_deep_value",
        "test_a_self_referencing_class_decodes_and_encodes_a_deep_value",
    )
)

GROUPS: dict[str, Group] = {
    "runtime": Group(
        sources=("_fiber.py", "_core.py", "_primitives.py", "_waiters.py", "_for_each.py"),
        tests=_RUNTIME_TESTS,
        deselect=(
            "interleave/test_harness.py::test_a_simulated_thread_resumes_through_the_scheduler",
            # Reads a process-wide metric, which mutmut's second in-process run finds updated.
            "oracle/test_effect_section4.py::test_frequency_state_is_the_live_map",
        ),
    ),
    "cause": Group(
        sources=("_cause_election.py", "cause.py", "exit.py"),
        tests=(
            "test_cause_*.py",
            "test_exit*.py",
            "test_error_combinators.py",
            "oracle/test_cause*.py",
            "oracle/test_exit.py",
            "oracle/test_effect_errors.py",
        ),
        deselect=(
            "test_cause_recovery.py::test_only_the_ports_of_effects_electing_sites_elect_defects",
        ),
    ),
    "scope": Group(
        sources=("scope.py", "_effect_resources.py"),
        tests=(
            "test_scope*.py",
            "test_resource_edges.py",
            "test_resources_in_acquire.py",
            "test_user_callbacks.py",
            "test_use_after_release.py",
            "oracle/test_scope.py",
            "oracle/test_resource.py",
            "oracle/test_effect_finalizers.py",
            "oracle/test_effect_cleanup_registration.py",
            "oracle/test_effect_interruption.py",
        ),
    ),
    "stream": Group(
        sources=(
            "pull.py",
            "channel/_channel.py",
            "channel/_loop.py",
            "channel/_upstream.py",
            "channel/_run.py",
            "channel/_merge.py",
            "stream/_stream.py",
            "stream/_run.py",
            "stream/_concat.py",
        ),
        tests=(
            "test_stream*.py",
            "test_channel*.py",
            "test_sink.py",
            "oracle/test_stream*.py",
            "oracle/test_channel*.py",
            "oracle/test_sink.py",
            "oracle/test_pull.py",
        ),
    ),
    "schema": Group(
        sources=(
            "schema/_parse.py",
            "schema/ast/_base.py",
            "schema/ast/_steps.py",
            "schema/ast/_result.py",
            "schema/ast/_check.py",
        ),
        tests=_SCHEMA_TESTS,
        deselect=_SCHEMA_DESELECT,
    ),
    "schema-composites": Group(
        sources=(
            "schema/ast/_objects.py",
            "schema/ast/_arrays.py",
            "schema/ast/_union.py",
            "schema/ast/_candidates.py",
        ),
        tests=_SCHEMA_TESTS,
        deselect=_SCHEMA_DESELECT,
    ),
}


def _test_paths(group: Group) -> list[str]:
    paths = sorted({p for pattern in group.tests for p in (ROOT / "tests").glob(pattern)})
    missing = [t for t in group.tests if not any((ROOT / "tests").glob(t))]
    if missing:
        raise SystemExit(f"no test file matches {missing}")
    return [str(p.relative_to(ROOT)) for p in paths]


def _toml_list(values: list[str]) -> str:
    return "[" + ", ".join(json.dumps(v) for v in values) + "]"


def prepare(name: str) -> Path:
    """The group's work directory: links to ``src`` and ``tests`` and a ``pyproject.toml``
    with the project's pytest settings and the group's mutmut settings."""
    group = GROUPS[name]
    work = WORK / name
    work.mkdir(parents=True, exist_ok=True)
    for linked in ("src", "tests"):
        link = work / linked
        if not link.is_symlink():
            link.symlink_to(ROOT / linked, target_is_directory=True)
    selection = _test_paths(group)
    for test in group.deselect:
        selection += ["--deselect", f"tests/{test}"]
    project = (ROOT / "pyproject.toml").read_text()
    if "[tool.mutmut]" in project:
        raise SystemExit("pyproject.toml has a [tool.mutmut] table; scripts/mutation.py owns it")
    type_check = [sys.executable, str(Path(__file__).resolve()), "pyright"]
    config = "\n".join(
        [
            "",
            "[tool.mutmut]",
            'source_paths = ["src/"]',
            f"only_mutate = {_toml_list([f'src/pyfect/{s}' for s in group.sources])}",
            f"pytest_add_cli_args_test_selection = {_toml_list(selection)}",
            # One hypothesis seed, so every mutant meets the same examples.
            'pytest_add_cli_args = ["-p", "no:randomly", "-p", "no:cacheprovider", '
            '"--hypothesis-seed=0"]',
            f"type_check_command = {_toml_list(type_check)}",
            # A mutant that loops forever is stopped after twice its tests' CPU time (mutmut's
            # default, 15 times, let one runtime mutant spin for two hours).
            "timeout_multiplier = 2.0",
            "timeout_constant = 30.0",
            "",
        ]
    )
    (work / "pyproject.toml").write_text(project + config)
    (work / "pyrightconfig.json").write_text(json.dumps(_pyright_config(group), indent=2))
    return work


def _pyright_config(group: Group) -> dict[str, object]:
    """The project's pyright settings over the mutated modules, so a mutant pyright rejects
    counts as caught (by the check every change passes). mutmut's generated trampolines pass
    an untyped dict and carry ``# type: ignore`` markers, which these two settings allow."""
    settings: dict[str, object] = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"][
        "pyright"
    ]
    settings.pop("exclude", None)
    return {
        **settings,
        "include": [f"mutants/src/pyfect/{s}" for s in group.sources],
        "venvPath": str(ROOT),
        "venv": ".venv",
        "reportUnnecessaryTypeIgnoreComment": False,
        "reportUnknownArgumentType": False,
    }


def run(names: list[str], max_children: int, survivors: bool) -> int:
    """mutmut keeps every result whose function did not change; ``survivors`` tests the
    surviving mutants again (mutmut does not rerun them for new tests)."""
    failed = 0
    _, surviving = collect(names)
    for name in names:
        work = prepare(name)
        again = [
            mutant
            for source in GROUPS[name].sources
            for mutant in surviving.get(_module(source), [])
        ]
        if survivors and not again:
            continue
        print(f"== {name}", flush=True)
        done = subprocess.run(
            [
                sys.executable,
                *("-m", "mutmut", "run", "--max-children", str(max_children)),
                *(again if survivors else ()),
            ],
            cwd=work,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        failed |= done.returncode
    return failed


@dataclass(slots=True)
class Score:
    killed: int = 0
    typed: int = 0
    """Of ``killed``, those pyright rejected (so no test ran)."""
    survived: int = 0
    skipped: int = 0
    unchecked: int = 0

    @property
    def total(self) -> int:
        return self.killed + self.survived

    @property
    def percent(self) -> float:
        return 100.0 * self.killed / self.total if self.total else 100.0


# mutmut's exit codes (mutmut.stats.status_by_exit_code), by how the score counts them.
_KILLED = {1, 3, 36, 37, -24, 24, 152, 255, -11, -9}
_SURVIVED = {0, 5, 33, 35}
_SKIPPED = {34}
_TYPE_CHECKED = 37


def _module(source: str) -> str:
    return "pyfect." + source.removesuffix(".py").replace("/", ".")


def collect(names: list[str]) -> tuple[dict[str, Score], dict[str, list[str]]]:
    """Every module's score and surviving mutants, from the groups' mutmut results."""
    scores: dict[str, Score] = {}
    survivors: dict[str, list[str]] = {}
    for name in names:
        for source in GROUPS[name].sources:
            module = _module(source)
            score = scores.setdefault(module, Score())
            meta = WORK / name / "mutants" / "src" / "pyfect" / f"{source}.meta"
            if not meta.exists():
                continue
            codes: dict[str, int | None] = json.loads(meta.read_text())["exit_code_by_key"]
            for mutant, code in sorted(codes.items()):
                if code is None:
                    score.unchecked += 1
                elif code in _KILLED:
                    score.killed += 1
                    score.typed += code == _TYPE_CHECKED
                elif code in _SKIPPED:
                    score.skipped += 1
                elif code in _SURVIVED:
                    score.survived += 1
                    survivors.setdefault(module, []).append(mutant)
                else:
                    raise SystemExit(f"{mutant}: unknown mutmut exit code {code}")
    return scores, survivors


def _group_of(module: str) -> str:
    source = module.removeprefix("pyfect.").replace(".", "/") + ".py"
    return next(name for name, group in GROUPS.items() if source in group.sources)


def report(names: list[str], diffs: bool) -> int:
    scores, survivors = collect(names)
    print(
        f"{'module':34} {'score':>7} {'killed':>7} {'pyright':>8} {'survived':>9} {'unchecked':>10}"
    )
    for module, s in scores.items():
        counts = f"{s.killed:7} {s.typed:8} {s.survived:9} {s.unchecked:10}"
        print(f"{module:34} {s.percent:6.1f}% {counts}")
    for module, mutants in survivors.items():
        print(f"\n{module}: {len(mutants)} surviving")
        for mutant in mutants:
            if diffs:
                shown = subprocess.run(
                    [sys.executable, "-m", "mutmut", "show", mutant],
                    cwd=WORK / _group_of(module),
                    capture_output=True,
                    text=True,
                    check=True,
                )
                print(shown.stdout)
            else:
                print(f"  {mutant}")
    return 0


def check(names: list[str], update: bool) -> int:
    """Compare the groups' scores with the baseline, which holds each module's score rounded
    down to a whole percent (so a timeout's chance alone does not fail the check)."""
    scores, _ = collect(names)
    unchecked = [m for m, s in scores.items() if s.unchecked or not s.total]
    if unchecked:
        print(f"not every mutant was tested in {unchecked}; run `scripts/mutation.py run` first")
        return 1
    current = {module: round(s.percent, 1) for module, s in scores.items()}
    baseline: dict[str, int] = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    if update:
        floors = {**baseline, **{m: math.floor(score) for m, score in current.items()}}
        every = [_module(source) for group in GROUPS.values() for source in group.sources]
        BASELINE.write_text(
            json.dumps({m: floors[m] for m in every if m in floors}, indent=2) + "\n"
        )
        return 0
    missing = sorted(set(current) - set(baseline))
    if missing:
        print(f"the baseline has no score for {missing}; record one with `check --update`")
        return 1
    dropped = {m: (baseline[m], current[m]) for m in current if current[m] < baseline[m]}
    for module, (was, now) in dropped.items():
        print(f"{module}: {now}% of mutants killed, below the baseline's {was}%")
    return 1 if dropped else 0


def _functions(path: str) -> list[tuple[str, int, int]]:
    """Each function mutmut generated in ``path``: its name and its first and last line."""
    tree = ast.parse(Path(path).read_text())
    return [
        (node.name, node.lineno, node.end_lineno or node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and "__mutmut_" in node.name
    ]


def pyright() -> int:
    """pyright's report on the mutated modules, keeping only the errors a mutant causes in its
    own body: a class's mutants are methods of it, so a mutant assigning ``None`` to an
    attribute widens the attribute's type for the original methods and the other mutants too.
    An error the unmutated copy (``..._mutmut_orig``) also has at the same place is that
    widening, not the mutant's own, and is dropped."""
    done = subprocess.run(
        [str(PYRIGHT), "--outputjson", "-p", "../pyrightconfig.json"],
        capture_output=True,
        text=True,
        check=False,
    )
    report = json.loads(done.stdout)
    errors: list[dict[str, Any]] = report["generalDiagnostics"]
    functions = {path: _functions(path) for path in {e["file"] for e in errors}}

    def place(error: dict[str, Any]) -> tuple[str, int] | None:
        line = error["range"]["start"]["line"] + 1
        for name, start, end in functions[error["file"]]:
            if start <= line <= end:
                return name, line - start
        return None

    def message(error: dict[str, Any]) -> str:
        # A type variable is named after its function: ``A@x_succeed__mutmut_1``.
        return re.sub(r"__mutmut_\w+", "__mutmut_", error["message"])

    seen = {(e["file"], place(e), message(e)) for e in errors}

    def own(error: dict[str, Any]) -> bool:
        where = place(error)
        if where is None or where[0].endswith("__mutmut_orig"):
            return False
        original = where[0].rpartition("__mutmut_")[0] + "__mutmut_orig"
        return (error["file"], (original, where[1]), message(error)) not in seen

    report["generalDiagnostics"] = [e for e in errors if own(e)]
    print(json.dumps(report))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Mutation testing of pyfect's core.")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("groups", nargs="*", metavar="GROUP", help=", ".join(GROUPS))
    run_parser.add_argument("--max-children", type=int, default=os.cpu_count() or 4)
    run_parser.add_argument("--survivors", action="store_true", help="test survivors again")
    report_parser = commands.add_parser("report")
    report_parser.add_argument("groups", nargs="*", metavar="GROUP")
    report_parser.add_argument("--diffs", action="store_true", help="each survivor's change")
    commands.add_parser("pyright", help="mutmut's type check (run in a group's mutants/)")
    check_parser = commands.add_parser("check")
    check_parser.add_argument("groups", nargs="*", metavar="GROUP")
    check_parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    if args.command == "pyright":
        return pyright()
    unknown = set(args.groups) - set(GROUPS)
    if unknown:
        parser.error(f"unknown groups {sorted(unknown)}; the groups are {', '.join(GROUPS)}")
    names: list[str] = args.groups or list(GROUPS)
    if args.command == "run":
        return run(names, args.max_children, args.survivors)
    if args.command == "report":
        return report(names, args.diffs)
    return check(names, args.update)


if __name__ == "__main__":
    sys.exit(main())
