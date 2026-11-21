# Contributing to pyfect

Thanks for helping. pyfect is a port of [Effect](https://effect.website) v4, so most work
is bringing one piece of Effect over faithfully and keeping pyright's inference exact.

## Setup

You need Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/tylergibbs1/pyfect
cd pyfect
uv sync
```

Then install the git hooks, once per clone (worktrees share `.git/hooks`, so they get them too):

```sh
uv run lefthook install
```

The pre-commit hook runs `ruff check --fix` and `ruff format` on the staged Python files and
stages the fixes; a lint error ruff can't fix stops the commit. The pre-push hook runs ruff
and pyright on the Python files the pushed commits add, where the working tree holds the
pushed version (CI checks the rest). Both are configured in `lefthook.yml`.

A clone that used the old `scripts/install-hooks` has `core.hooksPath` set, and Lefthook
won't install over it. Remove it first with `git config --unset core.hooksPath`.

Some tests and scripts read Effect's own source, at the commit CI pins (`EFFECT_COMMIT` in
`.github/workflows/ci.yml`). Make that checkout once, and again whenever the pin moves:

```sh
uv run python tests/_effect_ref.py
```

It prints where the checkout is: `~/pyfect-ref/effect-<commit>`, a worktree of
`~/pyfect-ref/effect`, cloned from Effect's repository if missing. Every clone and worktree
finds it without any setup, so branches that pin different Effects each find their own.
`PYFECT_EFFECT_REF` overrides it. Without a checkout these tests skip, and with a checkout
at another commit they fail and say how to fix it.

## The one check

A change is ready when this passes:

```sh
uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest
```

`tests/type_checks.py` is part of the pyright run. Its `assert_type` lines pin inferred
types, and its `# pyright: ignore[...]` lines must produce an error.

## Flaky tests

The tests run in parallel and in a random order (pytest-xdist and pytest-randomly), so a
test that fails once in a hundred runs rarely shows up on a pull request. The
`flakes-nightly` workflow looks for these every night, and you can start it by hand from the
Actions tab. It reruns ci.yml's five shards on exact CPython patches (3.13's latest, 3.14's
latest and 3.14.0) and extras.yml's free-threaded suites
(`tests/free_threaded_suites.txt`) on 3.14t. Each job keeps starting rounds for 40 minutes.
Every round uses a new seed, and every second round runs beside two busy processes that load
the CPUs. Nothing is retried or skipped, and the 5 s limit stays. The run fails if any test
failed even once.

The run's summary lists each failed test with its job, round, seed and load, and the
command that repeats that order. The `flakes-report` artifact holds the summary and the
logs of the rounds that failed. To repeat a failure, run the same shard with the same seed
on the same Python (`+gil`, which needs uv 0.9.8 or later, keeps uv off the free-threaded
build):

```sh
uv run --python 3.14.10+gil pytest -q -n 4 --shard=2/5 -p randomly --randomly-seed=1238892984
```

A free-threaded failure repeats with the job's own environment: a 3.14t venv holding pyfect,
pytest, pytest-xdist and pytest-randomly, run with `PYTHON_GIL=0` on the files in
`tests/free_threaded_suites.txt`, with the seed added.

The seed fixes the order of the tests, but not which worker runs which test. A race may
need several tries. Run the one test in a shell loop, with one `python -c "while True: pass" &`
per spare CPU to keep the CPUs busy.

## Porting from Effect

1. Read the Effect module and its tests (`packages/effect/src` and `packages/effect/test`
   in [Effect's repo](https://github.com/Effect-TS/effect)). Effect's behavior is the spec.
2. Port its test cases to `tests/oracle/test_<module>.py`: one pytest per Effect test
   title, with the title in the docstring. A case you leave out gets a one-line reason.
3. Implement it in `src/pyfect/`, in snake_case. Combinators that remove something from a
   type (`catch_tag`, `provide`) are curried functions used with `.pipe(...)`; the rest are
   methods. [`CLAUDE.md`](CLAUDE.md) lists the typing and runtime rules.
4. Add `assert_type` pins for public APIs whose types matter.
5. Update [`docs/PARITY.md`](docs/PARITY.md) if the change moves coverage.

## Fixing a bug

Write a failing test first, then fix it. Then ask why the bug was easy to write and change
the code (a type, a safer API, a test helper) so that kind of bug can't come back.

## Mutation testing

Tests must catch bugs, not just run code. `scripts/mutation.py` uses
[mutmut](https://github.com/boxed/mutmut) to plant small bugs in the core (the fiber
runtime, causes and exits, scopes, the stream and channel core, schema parsing) and runs
the tests that reach each one:

```sh
uv run python scripts/mutation.py run [GROUP...]   # every group in GROUPS by default
uv run python scripts/mutation.py report --diffs   # score per module, each survivor's change
uv run python scripts/mutation.py check            # fails below scripts/mutation_baseline.json
```

A mutant pyright rejects counts as caught. A surviving one is a missing test: add a behaviour
test that fails with it, in a file the group's test globs match. If the mutant cannot
change behaviour (an equivalent mutant), end the line with
`# pragma: no mutate, <why it is equivalent>`. When scores go up, record them with
`check --update`. The `mutation` workflow runs this weekly and on demand.

## Docs

The site lives in `website/` ([pyfect.dev](https://pyfect.dev)). Every Python example is a
file in `website/snippets/` that pyright checks and pytest runs.

```sh
cd website && bun install && bun run generate:api && bun run dev
```

## Where to start

Issues labelled
[good first issue](https://github.com/tylergibbs1/pyfect/labels/good%20first%20issue) are
small and self-contained. `docs/PARITY.md` lists what Effect has that pyfect does not yet.
