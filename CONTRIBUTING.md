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

## The one check

A change is ready when this passes:

```sh
uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest
```

`tests/type_checks.py` is part of the pyright run. Its `assert_type` lines pin inferred
types, and its `# pyright: ignore[...]` lines must produce an error.

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
