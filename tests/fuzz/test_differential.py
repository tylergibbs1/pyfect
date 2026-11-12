"""pyfect's parsers answer the checked-in corpus as Effect's do.

``effect_answers.json`` is what effect_oracle.ts (Effect 4.1.2 under Node) answers
for every corpus input of a parser Effect also has; regenerate it after changing
the corpus with ``PYFECT_EFFECT_REF=... python -m fuzz --differential --write``
(from ``tests/``).
"""

import json

from . import differential
from ._harness import CORPUS
from .targets import TARGETS


def _rows() -> list[tuple[str, str, object]]:
    rows = json.loads(differential.ANSWERS.read_text(encoding="utf-8"))
    return [(parser, text, answer) for parser, text, answer in rows]


def test_the_answers_cover_the_corpus():
    inputs = differential.corpus_inputs((name, CORPUS / name) for name in TARGETS)
    assert [(parser, text) for parser, text, _ in _rows()] == inputs, (
        "the corpus changed: regenerate effect_answers.json (python -m fuzz --differential --write)"
    )


def test_pyfect_answers_as_effect_does():
    rows = _rows()
    found = differential.differences(
        [(parser, text) for parser, text, _ in rows], [answer for _, _, answer in rows]
    )
    assert not found, found[:5]
