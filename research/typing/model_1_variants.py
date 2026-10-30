"""Question: how should a ``Model.Class`` (Effect's ``schema/Model``) be declared
so each variant's type is known and a repository's ``insert`` / ``update`` /
``find_by_id`` take and return the right variant?

Effect computes every variant's struct from one field map with mapped types
(``ExtractFields<V, Fields>``). Pyright has none, so:

Q1. Can anything compute ``User.insert``'s Type from the field declarations?
Q2. Can a generic base ``Class[Insert, Update, ...]`` (TypedDict arguments,
    defaulted) type ``User.insert`` through a descriptor reading the owner?
Q3. Does ``make_repository(User, ...)`` then infer the select, insert and
    update types?
Q4. Can a field absent from the select variant be declared so the class's
    ``__init__`` does not take it?
Q5. Can ``find_by_id``'s parameter come from ``id_column="id"``?
Q6. Can ``VariantSchema.make(...).Class`` (a class built at run time) be a
    base class pyright treats as a ``dataclass_transform`` class?

Run: ``uv run pyright -p research/typing research/typing/model_1_variants.py``.

Answers:

Q1. No. Per-field types can be carried (``Field[Select, Insert, ...]``), but no
    spelling projects a class onto the fields present in one variant: there
    are no mapped types, and a TypedDict's keys cannot be computed.
Q2. Yes. A non-data descriptor assigned without annotation (so not a
    dataclass field) whose ``__get__`` takes ``owner: type[Class[I, ...]]``
    solves ``I`` from the subclass's base arguments, so ``User.insert`` is
    ``Variant[UserInsert]``. Without arguments the defaults
    (``Mapping[str, object]``) apply. A ``ClassVar`` cannot hold the class's
    TypeVars, so a descriptor it must be.
Q3. Yes, through a classmethod: ``Class.__variants__(cls) -> Variants[Self, I, U]``
    and a protocol ``ModelType[A, I, U]`` with ``__variants__(self) -> Variants[A, I, U]``
    solve all three from ``type[User]``. A protocol over the ``insert`` /
    ``update`` descriptors does not match (pyright wants them ``ClassVar``s,
    which cannot hold TypeVars), and a ``__call__`` member gives ``A = Any``.
Q4. Yes: an unannotated assignment (``password = Model.field_only("insert")(S.String)``)
    is no dataclass field, so neither ``__init__`` nor instances have it; the
    run time reads the variant field from the class body.
Q5. No: a string literal cannot index a class's attribute types, and Effect's
    API takes a column name. ``find_by_id`` / ``delete`` take ``object``,
    encoded by the id field's schema (a wrong id is a ``SchemaError``), and
    ``make_repository`` checks the column at the boundary (``ValueError``).
Q6. Yes: a base class expression of type ``type[Class]`` is accepted and its
    ``dataclass_transform`` applies (``Dynamic(nam=...)`` is rejected). The
    variant attributes such a toolkit adds at run time (``User.b``) have no
    static type; ``toolkit.extract(User, "b")`` is the typed way to them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import (
    Any,
    Generic,
    NotRequired,
    Protocol,
    Self,
    TypedDict,
    TypeVar,
    assert_type,
    dataclass_transform,
    overload,
)

I = TypeVar("I", default=Mapping[str, object])
U = TypeVar("U", default=Mapping[str, object])
A_co = TypeVar("A_co", covariant=True)


class Variant(Generic[A_co]):
    def make(self, input: A_co) -> A_co:  # pyright: ignore[reportGeneralTypeIssues]
        return input


class _InsertAccessor:
    @overload
    def __get__[X](self, instance: None, owner: type[Class[X, Any]]) -> Variant[X]: ...
    @overload
    def __get__[X](self, instance: object, owner: type[Class[X, Any]]) -> Variant[X]: ...
    def __get__(self, instance: object, owner: type) -> Any:
        return Variant[Any]()


class _UpdateAccessor:
    def __get__[X](self, instance: object, owner: type[Class[Any, X]]) -> Variant[X]:
        return Variant[X]()


def field[A](spec: FieldSpec[A]) -> A:
    raise NotImplementedError


class FieldSpec(Generic[A_co]):
    pass


class Absent:
    pass


def generated_by_db[A](schema: Callable[[], A]) -> FieldSpec[A]:
    return FieldSpec()


def field_only_insert[A](schema: Callable[[], A]) -> FieldSpec[Absent]:
    return FieldSpec()


@dataclass_transform(kw_only_default=True, frozen_default=True, field_specifiers=(field,))
class Class(Generic[I, U]):
    insert = _InsertAccessor()
    update = _UpdateAccessor()

    @classmethod
    def __variants__(cls) -> Variants[Self, I, U]:
        raise NotImplementedError


class Variants(Generic[A_co, I, U]):
    pass


# Q2 ------------------------------------------------------------------------------------


class UserInsert(TypedDict):
    name: str
    created_at: NotRequired[float]


class UserUpdate(TypedDict):
    id: int
    name: str


class User(Class[UserInsert, UserUpdate]):
    id: int = field(generated_by_db(int))
    name: str
    created_at: float
    password = field_only_insert(str)  # Q4: no annotation, no dataclass field


assert_type(User.insert, Variant[UserInsert])
assert_type(User.update, Variant[UserUpdate])
User(id=1, name="a", created_at=1.0)
User(id=1, name="a", created_at=1.0, password="x")  # pyright: ignore[reportCallIssue]
User.insert.make({"name": "a"})
User.insert.make({"nam": "a"})  # pyright: ignore[reportArgumentType]


class Plain(Class):
    name: str


assert_type(Plain.insert, Variant[Mapping[str, object]])


# Q3 ------------------------------------------------------------------------------------


class ModelType(Protocol[A_co, I, U]):
    def __variants__(self) -> Variants[A_co, I, U]: ...


class Repository(Generic[A_co, I, U]):
    def insert(self, value: I) -> A_co:
        raise NotImplementedError

    def update(self, value: U) -> A_co:
        raise NotImplementedError


def make_repository[A, X, Y](model: ModelType[A, X, Y], *, id_column: str) -> Repository[A, X, Y]:
    return Repository()


repo = make_repository(User, id_column="id")
assert_type(repo, Repository[User, UserInsert, UserUpdate])
assert_type(repo.insert({"name": "a"}), User)
repo.insert({"id": 1})  # pyright: ignore[reportArgumentType]


# Q6 ------------------------------------------------------------------------------------


def make_toolkit() -> type[Class]:
    return Class


Toolkit = make_toolkit()


class Dynamic(Toolkit):
    name: str


Dynamic(name="a")
Dynamic(nam="a")  # pyright: ignore[reportCallIssue]
