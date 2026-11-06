"""Effect's ``Schema.Undefined`` for schemas whose wire form must match Effect's
(``RpcMessage.EncodedSchema``'s optional fields). Python has one absent value,
so its values are ``None``; ``Schema.Null`` stays a different layout."""

from __future__ import annotations

from typing import TypeIs

from pyfect.encoding.schema_binary._compile import UNDEFINED_ID
from pyfect.schema._declare import declare
from pyfect.schema._schema import Bottom


def _is_none(value: object) -> TypeIs[None]:
    return value is None


Undefined: Bottom[None] = declare(
    _is_none, expected="undefined", representation={"id": UNDEFINED_ID, "payload": None}
)
