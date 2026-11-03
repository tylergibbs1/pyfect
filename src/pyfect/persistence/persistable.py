"""Requests whose results can be stored (Effect's
``effect/persistence/Persistable``).

A persistable request names itself with ``primary_key()`` and carries the
schemas of its success and error, so its ``Exit`` can be written as JSON
and read back. ``Class`` makes the base class from the schemas, and the
request's types come from them::

    @dataclass(frozen=True)
    class GetUser(persistable.Class(success=User, error=S.String)):
        id: int

        def primary_key(self) -> str:
            return f"GetUser:{self.id}"

``GetUser(1)`` is a ``Request[User, str | PersistenceError | SchemaError]``:
a store may fail to read or write, or hold a value the schemas reject.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, ClassVar, Never, Protocol, TypeVar, cast

from pyfect import schema as S
from pyfect._core import Effect
from pyfect._json_value import JsonValue
from pyfect.batching._request import Request
from pyfect.duration import Duration
from pyfect.exit import Exit
from pyfect.persistence._error import PersistenceError

A_co = TypeVar("A_co", covariant=True)
E_co = TypeVar("E_co", covariant=True, default=Never)
R_co = TypeVar("R_co", covariant=True, default=Never)

type AnyCodec = S.Codec[Any, Any, Any, Any]
type _ExitCodec = S.Bottom[Exit[Any, Any], JsonValue, Any, Any]


class Persistable(Request[A_co, E_co | PersistenceError | S.SchemaError, R_co], ABC):
    """A request succeeding with ``A`` and failing with ``E`` (the types of
    its schemas, which need the services ``R``), stored under
    ``primary_key()``. Subclass ``Class(success=..., error=...)``."""

    __slots__ = ()

    _success_schema: ClassVar[AnyCodec]
    _error_schema: ClassVar[AnyCodec]
    _exit_codec: ClassVar[_ExitCodec | None]

    @abstractmethod
    def primary_key(self) -> str:
        """The key the request's result is stored under."""

    def _persistable_types(self) -> Exactly[A_co, E_co]:
        """Never called: lets ``persisted_cache`` read the request's success
        and error exactly (``Persistable.Success<K>`` / ``Error<K>``)."""
        raise NotImplementedError


class Exactly[A, E]:
    """Invariant in ``A`` and ``E`` (each is taken and given back), so
    matching a request's ``_persistable_types()`` pins its success and
    error instead of widening them to what else they meet."""

    __slots__ = ()

    def pin(self, success: A, error: E) -> tuple[A, E]:
        raise NotImplementedError


class HasPersistableTypes[A, E](Protocol):
    """A persistable request succeeding with exactly ``A`` and failing with
    exactly ``E`` (its schemas' types)."""

    def _persistable_types(self) -> Exactly[A, E]: ...


type AnyPersistable = Persistable[Any, Any, Any]

type TimeToLive[K, A, E] = Callable[[Exit[A, E], K], Duration]
"""How long to keep a request's outcome: a function of the ``Exit`` and
the request. Zero or less keeps nothing; infinity keeps it forever."""


def Class[A = None, E = Never, RR = Never](
    *,
    success: S.Codec[A, Any, RR, RR] | None = None,
    error: S.Codec[E, Any, RR, RR] | None = None,
) -> type[Persistable[A, E, RR]]:
    """The base class of a persistable request succeeding with ``success``'s
    values (default: ``None``) and failing with ``error``'s (default:
    never). Subclass it as a frozen dataclass and define
    ``primary_key()``."""
    success_schema: AnyCodec = S.Null if success is None else success
    error_schema: AnyCodec = S.Never if error is None else error

    class Base(Persistable[Any, Any, Any]):
        __slots__ = ()
        _success_schema = success_schema
        _error_schema = error_schema
        _exit_codec = None

    return cast("type[Persistable[A, E, RR]]", Base)


def success_schema[A](request: Persistable[A, Any, Any]) -> S.Codec[A, Any, Any, Any]:
    return type(request)._success_schema


def error_schema[E](request: Persistable[Any, E, Any]) -> S.Codec[E, Any, Any, Any]:
    return type(request)._error_schema


def exit_schema[A, E](
    request: Persistable[A, E, Any],
) -> S.ExitSchema[A, E, Any, Any, Any, Any]:
    """The schema of the request's ``Exit``: its success, its error, or a
    defect."""
    cls = type(request)
    return S.Exit(cls._success_schema, cls._error_schema, S.Defect())


def _exit_codec(request: AnyPersistable) -> _ExitCodec:
    """The JSON codec of the request's ``Exit``, made once per class."""
    cls = type(request)
    codec = cls._exit_codec
    if codec is None:
        codec = S.to_codec_json(exit_schema(request))
        cls._exit_codec = codec
    return codec


def serialize_exit[A, E, R](
    request: Persistable[A, E, R], exit: Exit[A, E]
) -> Effect[JsonValue, S.SchemaError, R]:
    """``exit`` as JSON, by the request's schemas."""
    return S.encode_effect(_exit_codec(request))(exit)


def deserialize_exit[A, E, R](
    request: Persistable[A, E, R], encoded: object
) -> Effect[Exit[A, E], S.SchemaError, R]:
    """The ``Exit`` that ``encoded`` holds, by the request's schemas."""
    return S.decode_unknown_effect(_exit_codec(request))(encoded)


__all__ = [
    "AnyCodec",
    "AnyPersistable",
    "Class",
    "Exactly",
    "HasPersistableTypes",
    "Persistable",
    "TimeToLive",
    "deserialize_exit",
    "error_schema",
    "exit_schema",
    "serialize_exit",
    "success_schema",
]
