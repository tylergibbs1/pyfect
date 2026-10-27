# pyright: strict
"""Schema exp 2: declaring structs. What can pyright infer for each spelling?

(A) schema *types* as annotations, read through descriptors (``id: S.Int``);
(B) a field specifier with the Python type written out (``id: int = field(S.Int)``);
(C) plain Python types (``id: int``), the schema derived at run time;
(D) a Struct over a dict or keyword arguments.

Measured (every line below passes):
(A) works: pyright synthesizes ``__init__(id: int, ...)`` from the descriptors'
    ``__set__`` and reads attributes through ``__get__``, generic ones included
    (``Array[String]`` via a self-typed ``__get__``). But every schema must then be
    a *type*: checks, transformations, unions and literals need a parallel
    type-level vocabulary next to the value-level one, and ``__set__`` on a
    covariant ``T`` needs an ignore.
(B) works and is checked: ``wrong: str = field(Int())`` is an error, any schema
    expression fits, a field without ``default=`` stays required.
(C) Type is exact for free (it is the annotation) but ``Annotated[float, schema]``
    is not checked against the schema's Type.
(D) widens: ``struct(id=Int(), name=String())`` is ``dict[str, int | str]``.
No spelling gives a precise *Encoded* for a struct: pyright has no mapped
types. ``Mapping[str, object]`` is the honest Encoded (``dict[str, object]``
would reject TypedDicts and ``dict[str, int]`` inputs, dict being invariant).
Chosen: (C) for the common case, (B) when the schema is not the annotation's
default; see docs/SCHEMA_DESIGN.md.

Run: uv run pyright -p research/typing research/typing/schema_2_struct.py
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import (
    Annotated,
    Any,
    ClassVar,
    Generic,
    Never,
    NotRequired,
    Protocol,
    Self,
    TypedDict,
    TypeVar,
    assert_type,
    dataclass_transform,
    overload,
)

T = TypeVar("T", covariant=True)
E = TypeVar("E", covariant=True, default=T)
RD = TypeVar("RD", covariant=True, default=Never)
RE = TypeVar("RE", covariant=True, default=Never)


class Codec(Generic[T, E, RD, RE]):
    pass


# A class used as a schema matches this protocol through a classmethod: one
# parameter type covers codecs and Class subclasses alike.
class Schemable(Protocol[T, E, RD, RE]):
    def codec(self) -> Codec[T, E, RD, RE]: ...


class Leaf(Codec[T, E, RD, RE]):
    def codec(self) -> Codec[T, E, RD, RE]:
        return self


def decode_unknown_sync[A](schema: Schemable[A, Any, Never, Any]) -> Callable[[object], A]: ...


# ---------------------------------------------------------------- (A) descriptors


class Field(Leaf[T, E, RD, RE]):
    """A schema that, as a class attribute annotation, reads as its Type."""

    @overload
    def __get__(self, obj: None, owner: type, /) -> Self: ...
    @overload
    def __get__(self, obj: object, owner: type, /) -> T: ...
    def __get__(self, obj: object, owner: type, /) -> Self | T: ...
    def __set__(self, obj: object, value: T, /) -> None: ...  # pyright: ignore[reportGeneralTypeIssues]


class String(Field[str]): ...


class Int(Field[int]): ...


class NumberFromString(Field[float, str]): ...


S_co = TypeVar("S_co", bound=Codec[Any, Any, Any, Any], covariant=True)


class Array(Field[Any, Any, Any, Any], Generic[S_co]):
    """``Array[String]``: the item schema is a type argument."""

    @overload
    def __get__(self, obj: None, owner: type, /) -> Self: ...
    @overload
    def __get__[A](self: Array[Codec[A, Any, Any, Any]], obj: object, owner: type, /) -> tuple[A, ...]: ...
    def __get__(self, obj: object, owner: type, /) -> Any: ...
    def __set__[A](self: Array[Codec[A, Any, Any, Any]], obj: object, value: tuple[A, ...], /) -> None: ...


class OptionalKey(Field[Any, Any, Any, Any], Generic[S_co]):
    @overload
    def __get__(self, obj: None, owner: type, /) -> Self: ...
    @overload
    def __get__[A](self: OptionalKey[Codec[A, Any, Any, Any]], obj: object, owner: type, /) -> A | None: ...
    def __get__(self, obj: object, owner: type, /) -> Any: ...
    def __set__[A](self: OptionalKey[Codec[A, Any, Any, Any]], obj: object, value: A | None, /) -> None: ...


class _Missing: ...


MISSING: Any = _Missing()


@dataclass_transform(kw_only_default=True, frozen_default=True)
class Class:
    @classmethod
    def codec(cls) -> Codec[Self, dict[str, object]]: ...


class UserA(Class):
    id: Int
    name: String
    tags: Array[String]
    score: NumberFromString
    nick: OptionalKey[String] = MISSING


assert_type(UserA(id=1, name="a", tags=("x",), score=1.5).id, int)
assert_type(UserA(id=1, name="a", tags=("x",), score=1.5).tags, tuple[str, ...])
assert_type(UserA(id=1, name="a", tags=("x",), score=1.5).nick, str | None)
UserA(id="1", name="a", tags=("x",), score=1.5)  # pyright: ignore[reportArgumentType]
UserA(id=1, name="a", tags=(1,), score=1.5)  # pyright: ignore[reportArgumentType]
UserA(name="a", tags=(), score=1.5)  # pyright: ignore[reportCallIssue]
assert_type(decode_unknown_sync(UserA)({}), UserA)
assert_type(decode_unknown_sync(String())(1), str)
assert_type(UserA.codec(), Codec[UserA, dict[str, object]])

# ------------------------------------------------- (B) field specifier, type written out


def field[A](schema: Codec[A, Any, Any, Any]) -> A: ...


@dataclass_transform(kw_only_default=True, frozen_default=True, field_specifiers=(field,))
class ClassB:
    @classmethod
    def codec(cls) -> Codec[Self, dict[str, object]]: ...


class UserB(ClassB):
    id: int = field(Int())
    name: str = field(String())
    wrong: str = field(Int())  # pyright: ignore[reportAssignmentType]


UserB(id=1, name="a", wrong="w")
UserB(id=1, name="a")  # pyright: ignore[reportCallIssue]  (no default=: still required)


# ------------------------------------------------------- (C) plain Python annotations


@dataclass_transform(kw_only_default=True, frozen_default=True)
class ClassC:
    fields: ClassVar[dict[str, Codec[Any, Any, Any, Any]]]


class Check: ...


class UserC(ClassC):
    id: int
    name: Annotated[str, Check()]  # the check is not tied to str by pyright
    score: Annotated[float, NumberFromString()]  # nor the schema's Type to float


assert_type(UserC(id=1, name="a", score=1.0).score, float)


# ----------------------------------------------------------------- (D) Struct(**fields)


def struct[A, I](**fields: Codec[A, I, Never, Never]) -> Codec[dict[str, A], dict[str, I]]: ...


assert_type(struct(id=Int(), name=String()), Codec[dict[str, int | str], dict[str, int | str]])


# ------------------------------------- (B) + (C) together, as chosen, with defaults


@overload
def field2[A](schema: Codec[A, Any, Never, Never]) -> A: ...
@overload
def field2[A](schema: Codec[A, Any, Never, Never], *, default: A) -> A: ...
def field2(schema: Codec[Any, Any, Never, Never], *, default: Any = None) -> Any: ...


@dataclass_transform(kw_only_default=True, frozen_default=True, field_specifiers=(field2,))
class ClassBC:
    @classmethod
    def codec(cls) -> Codec[Self, Mapping[str, object]]: ...


class Db: ...


class NeedsDb(Field[int, str, Db]): ...


class UserBC(ClassBC):
    id: int
    score: float = field2(NumberFromString())
    count: int = field2(Int(), default=0)
    nick: str | None = None
    loaded: int = field2(NeedsDb())  # pyright: ignore[reportArgumentType]  (services rejected)


UserBC(id=1, score=1.0)  # pyright: ignore[reportCallIssue]
assert_type(decode_unknown_sync(UserBC)({}), UserBC)


# A TypedDict declares a Struct: Type exact, NotRequired is an optional key.
class UserTD(TypedDict):
    id: int
    nick: NotRequired[str]


def struct_of[TD: Mapping[str, object]](td: type[TD]) -> Codec[TD, Mapping[str, object]]: ...


assert_type(struct_of(UserTD), Codec[UserTD, Mapping[str, object]])
