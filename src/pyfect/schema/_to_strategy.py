"""``to_strategy``: a Hypothesis strategy for a schema's decoded values
(Effect's ``Arbitrary.schema``; Hypothesis is the runner, so Effect's
``checkEffect`` / ``sampleEffect`` are ``@given`` and ``.example()``).

Needs the ``pyfect-dev[hypothesis]`` extra; importing ``pyfect.schema`` does
not import Hypothesis.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyfect.schema._schema import Codec

if TYPE_CHECKING:
    from hypothesis.strategies import SearchStrategy


def to_strategy[T](schema: Codec[T, object, object, object], /) -> SearchStrategy[T]:
    """Values of ``schema``'s decoded side that pass its checks and that
    ``schema`` encodes (a JSON string holds no ``NaN``, say).

    Common checks (bounds, lengths, sizes, patterns, integers) shape what is
    drawn; every check also filters it. A declaration is drawn with its
    ``to_arbitrary`` annotation (its type parameters' strategies in, a
    strategy out), else through its ``to_codec_arbitrary``, ``to_codec_json``
    or ``to_codec`` link. Raises ``ValueError`` when the schema has no
    finite value or a declaration says neither."""
    from pyfect.schema._strategy import derive

    return derive(schema.__codec__().ast)
