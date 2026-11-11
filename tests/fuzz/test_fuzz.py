"""Every fuzz target replays its corpus, then runs on Hypothesis's inputs.

``PYFECT_FUZZ_EXAMPLES`` sets how many inputs each target gets (default 40);
``python -m fuzz <target>`` (from ``tests/``) fuzzes one with Atheris, guided by
coverage. A crash found either way is minimized and added to the corpus, with a
regression test next to the fix.
"""

import os
import re
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ._harness import check, corpus
from .targets import MODULES, TARGETS, Target

_EXAMPLES = int(os.environ.get("PYFECT_FUZZ_EXAMPLES", "40"))
_ALL = sorted(TARGETS.values(), key=lambda found: found.name)


def _seeds(found: Target) -> list[bytes]:
    return [path.read_bytes() for path in corpus(found.name)]


def _mutated(seeds: list[bytes]) -> st.SearchStrategy[bytes]:
    """A seed with a few bytes replaced, inserted or deleted."""

    @st.composite
    def mutate(draw: st.DrawFn) -> bytes:
        data = bytearray(draw(st.sampled_from(seeds)))
        for _ in range(draw(st.integers(1, 4))):
            at = draw(st.integers(0, len(data)))
            match draw(st.integers(0, 2)):
                case 0 if at < len(data):
                    data[at] = draw(st.integers(0, 255))
                case 1:
                    data[at:at] = draw(st.binary(min_size=1, max_size=8))
                case _:
                    del data[at : at + draw(st.integers(1, 8))]
        return bytes(data)

    return mutate()


@pytest.mark.parametrize("found", _ALL, ids=lambda found: found.name)
def test_the_corpus_replays(found: Target) -> None:
    seeds = _seeds(found)
    assert seeds, f"tests/fuzz/corpus/{found.name} has no seeds"
    for data in seeds:
        check(found, data)


@pytest.mark.parametrize("found", _ALL, ids=lambda found: found.name)
def test_no_input_crashes(found: Target) -> None:
    seeds = _seeds(found)
    inputs = st.binary(max_size=512) | _mutated(seeds) if seeds else st.binary(max_size=512)

    @settings(
        max_examples=_EXAMPLES,
        deadline=None,
        database=None,
        suppress_health_check=(HealthCheck.too_slow, HealthCheck.data_too_large),
    )
    @given(inputs)
    def run(data: bytes) -> None:
        check(found, data)

    run()


def test_ci_fuzzes_every_target_module() -> None:
    """fuzz.yml runs one job per group (``python -m fuzz --group``): a new
    targets module needs its group there, or no job fuzzes it."""
    workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "fuzz.yml"
    matrix = re.search(r"(?m)^\s+group: \[(.*)\]$", workflow.read_text(encoding="utf-8"))
    assert matrix, "fuzz.yml has no group matrix"
    groups = [group.strip() for group in matrix.group(1).split(",")]
    for module in MODULES:
        name = module.__name__.rsplit(".", 1)[-1]
        assert any(name.startswith(group) for group in groups), f"no fuzz.yml group runs {name}"
