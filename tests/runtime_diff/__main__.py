"""Compare pyfect's runtime with Effect's on generated cases (a program and the
``MaxOpsBeforeYield`` it runs under), from ``tests/`` (Node 24 and
``PYFECT_EFFECT_REF`` needed):

    python -m runtime_diff --fresh 500 [--seed N]    # fail on the first difference, shrunk
    python -m runtime_diff --survey 2000 [--seed N]  # every difference in a batch, smallest first
    python -m runtime_diff --write 300 [--seed N]    # add cases and Effect's answers
    python -m runtime_diff --add CASES.json          # add these cases (a JSON list) to it
    python -m runtime_diff --refresh                 # ask Node again for every corpus case

``--write`` and ``--add`` keep the corpus' cases and add new ones;
test_runtime_differential.py replays the corpus in every pytest run, without Node.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from hypothesis import HealthCheck, Phase, given, seed, settings

from .generate import cases
from .oracle import EffectOracle, case_from_json, case_json, difference, read_corpus, write_corpus
from .program import Case, Json


def _settings(count: int, *, shrink: bool) -> settings:
    return settings(
        max_examples=count,
        database=None,
        deadline=None,
        suppress_health_check=list(HealthCheck.__members__.values()),
        phases=list(Phase) if shrink else [Phase.generate],
    )


def sample(count: int, at: int, max_leaves: int) -> list[Case]:
    """``count`` distinct cases Hypothesis generates from seed ``at``."""
    found: dict[str, Case] = {}

    @seed(at)
    @_settings(count, shrink=False)
    @given(cases(max_leaves))
    def collect(case: Case) -> None:
        found.setdefault(json.dumps(case_json(case)), case)

    collect()
    return list(found.values())


def fresh(count: int, at: int, max_leaves: int) -> None:
    with EffectOracle() as oracle:

        @seed(at)
        @_settings(count, shrink=True)
        @given(cases(max_leaves))
        def compare(case: Case) -> None:
            found = difference(case, oracle.answer(case))
            assert found is None, found

        compare()


def survey(count: int, at: int, max_leaves: int) -> int:
    found: list[str] = []
    with EffectOracle() as oracle:
        for case in sample(count, at, max_leaves):
            different = difference(case, oracle.answer(case))
            if different is not None:
                found.append(different)
    for different in sorted(found, key=len):
        print(different, end="\n\n")
    print(f"{len(found)} of {count} cases differ", file=sys.stderr)
    return 1 if found else 0


def write(new: list[Case], *, refresh: bool) -> None:
    """Add ``new`` cases Effect answers to the corpus, asking again for the
    kept ones when ``refresh``."""
    rows = read_corpus()
    known = {json.dumps(case_json(case)) for case, _ in rows}
    added = {json.dumps(case_json(c)): c for c in new if json.dumps(case_json(c)) not in known}
    with EffectOracle() as oracle:
        if refresh:
            rows = [(case, oracle.answer(case)) for case, _ in rows]
        rows.extend((case, oracle.answer(case)) for case in added.values())
    write_corpus(rows)
    print(f"corpus: {len(rows)} cases ({len(added)} new)", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m runtime_diff")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fresh", type=int, metavar="N")
    mode.add_argument("--survey", type=int, metavar="N")
    mode.add_argument("--write", type=int, metavar="N")
    mode.add_argument("--add", type=Path, metavar="CASES.json")
    mode.add_argument("--refresh", action="store_true")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--max-leaves", type=int, default=12)
    args = parser.parse_args()
    at: int = random.randrange(2**32) if args.seed is None else args.seed
    if args.add is None and not args.refresh:
        print(f"seed {at}", file=sys.stderr)
    if args.fresh is not None:
        fresh(args.fresh, at, args.max_leaves)
        return 0
    if args.survey is not None:
        return survey(args.survey, at, args.max_leaves)
    if args.add is not None:
        listed: list[dict[str, Json]] = json.loads(args.add.read_text(encoding="utf-8"))
        write([case_from_json(item) for item in listed], refresh=False)
        return 0
    new = [] if args.write is None else sample(args.write, at, args.max_leaves)
    write(new, refresh=args.refresh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
