"""Model ids made by the application (Effect's ``Model.UuidV4Insert``,
``UuidV7Insert``, ``UuidV4BytesInsert``): a UUID the ``insert`` variant's
``make`` generates when none is given."""

from __future__ import annotations

import os
import uuid
from typing import Any, Never, cast

from pyfect._core import Effect
from pyfect._uuid_v7 import v7_monotonic
from pyfect.clock import now_nanos
from pyfect.effect import sync
from pyfect.schema._schema import Codec
from pyfect.schema.variant_schema import Field, WithConstructorDefault, with_constructor_default


def _uuid_v7(millis: int) -> uuid.UUID:
    """RFC 9562 version 7 in the process-wide order (``pyfect._uuid_v7``): each sorts
    after the previous one, even within a millisecond or when the clock goes back."""
    return uuid.UUID(bytes=v7_monotonic(millis, os.urandom(16)))


def _generated[B](schema: Codec[B, Any, Any, Any], make: Effect[object]) -> Any:
    return with_constructor_default(cast("Effect[B, Never, Never]", make))(schema)


def UuidV4WithGenerate[B: str, I, RD, RE](
    schema: Codec[B, I, RD, RE], /
) -> WithConstructorDefault[B, I, RD, RE]:
    """``schema`` defaulting to a new random UUID's text."""
    return _generated(schema, sync(lambda: str(uuid.uuid4())))


def UuidV7WithGenerate[B: str, I, RD, RE](
    schema: Codec[B, I, RD, RE], /
) -> WithConstructorDefault[B, I, RD, RE]:
    """``schema`` defaulting to a new time-ordered UUID's text, its time
    read from the ``Clock``. Every such UUID in the process shares one order, so a
    ``Clock`` behind the latest timestamp used (a ``TestClock``) gives that timestamp."""
    return _generated(schema, now_nanos().map(lambda n: str(_uuid_v7(n // 1_000_000))))


def UuidV4BytesWithGenerate[B: bytes, I, RD, RE](
    schema: Codec[B, I, RD, RE], /
) -> WithConstructorDefault[B, I, RD, RE]:
    """``schema`` defaulting to a new random UUID's 16 bytes."""
    return _generated(schema, sync(lambda: uuid.uuid4().bytes))


def UuidV4Insert[B: str](schema: Codec[B, Any, Any, Any], /) -> Field[B]:
    """An id the application generates on insert: a UUID v4 by default in
    ``insert``, required in ``select``, ``update`` and ``json``."""
    return _insert(schema, UuidV4WithGenerate(schema))


def UuidV7Insert[B: str](schema: Codec[B, Any, Any, Any], /) -> Field[B]:
    """``UuidV4Insert`` with time-ordered UUIDs (v7)."""
    return _insert(schema, UuidV7WithGenerate(schema))


def UuidV4BytesInsert[B: bytes](schema: Codec[B, Any, Any, Any], /) -> Field[B]:
    """``UuidV4Insert`` for ids stored as 16 bytes."""
    return _insert(schema, UuidV4BytesWithGenerate(schema))


def _insert[B](schema: Codec[B, Any, Any, Any], insert: Codec[B, Any, Any, Any]) -> Field[B]:
    return Field({"select": schema, "insert": insert, "update": schema, "json": schema})
