"""Effect's ``Transferable.Uint8Array``, the event log's bytes on the wire.

``SchemaBinary`` writes it as ``S.Bytes``. Its JSON codec passes the
``Uint8Array`` through, so ``JSON.stringify`` writes an object of indexes,
``{"0":1,"1":2}``, where ``S.Bytes`` writes base64. Effect then refuses that
object when reading (``Expected Uint8Array``), which leaves its event log unable
to run over JSON; this reads it, so two pyfect peers can.
"""

from __future__ import annotations

from collections.abc import Mapping

from pyfect.exit import Exit, Success, fail
from pyfect.schema import ast
from pyfect.schema import transformation as T
from pyfect.schema._declare import instance_of
from pyfect.schema._options import ParseOptions
from pyfect.schema._primitives import Natural, String
from pyfect.schema._record import Record
from pyfect.schema._schema import Bottom
from pyfect.schema.issue import InvalidValue, Issue, reported


def _from_indexes(indexes: Mapping[str, int], options: ParseOptions) -> Exit[bytes, Issue]:
    try:
        return Success(bytes(indexes[str(i)] for i in range(len(indexes))))
    except (KeyError, ValueError):
        expected = {"expected": "an object of byte values by index"}
        return fail(InvalidValue(expected, reported(indexes, options)))


def _encode(value: bytes, _: ParseOptions) -> Exit[dict[str, int], Issue]:
    return Success({str(i): byte for i, byte in enumerate(value)})


_INDEXES = Record(String, Natural).ast


def _json_form(_: tuple[ast.AST, ...]) -> ast.Link:
    return ast.Link(_INDEXES, T.transform_effect(decode=_from_indexes, encode=_encode))


def _bytes_strategy(_: tuple[object, ...]) -> object:
    from pyfect.schema._strategy import st

    return st.binary()


TransferableBytes: Bottom[bytes] = instance_of(
    bytes,
    representation={"id": "effect/schema/Uint8Array", "payload": None},
    to_codec_json=_json_form,
    to_arbitrary=_bytes_strategy,
)
