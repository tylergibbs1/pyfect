"""How the synchronous adapters read a failed parse: a cause made only of
``SchemaError`` failures is a schema failure; anything else (a defect, an
interruption) is never turned into ``None``, ``False`` or ``Err``.

As in Effect, that raises a ``RuntimeError`` naming the adapter
(``"Sync adapter can only throw schema errors"``), chained from the cause's
first defect (else its squashed error), with the whole cause as a note.
"""

from __future__ import annotations

from typing import Never

from pyfect.cause import Cause, Fail
from pyfect.schema._error import SchemaError

SYNC = "Sync adapter can only throw schema errors"
OPTION = "Option adapter can only return none for schema issues"
RESULT = "Result adapter can only return schema issues"
GUARD = "Type guard adapter can only return false for schema issues"
ASSERTION = "Assertion adapter can only throw schema issues"
CONSTRUCTOR = "Constructor adapter can only throw schema issues"


def schema_error_of(cause: Cause[SchemaError], adapter: str) -> SchemaError:
    """The first ``SchemaError`` of a cause holding only those; otherwise
    raises ``RuntimeError(adapter)``."""
    errors = [r.error for r in cause.reasons if isinstance(r, Fail)]
    if errors and len(errors) == len(cause.reasons):
        return errors[0]
    error = RuntimeError(adapter)
    error.add_note("Cause:\n" + cause.pretty())
    raise error from (cause.find_defect() or cause.squash())


def raise_schema_failure(cause: Cause[SchemaError], adapter: str) -> Never:
    raise schema_error_of(cause, adapter)
