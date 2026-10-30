"""``Model.Class``: a schema class of the ``select`` variant whose other
variants are typed by the TypedDicts given as its type arguments::

    class UserInsert(TypedDict):
        name: str
        created_at: NotRequired[datetime]  # has a constructor default


    class User(Model.Class[UserInsert]):
        id: int = Model.field(Model.GeneratedByDb(S.Int))
        name: str
        created_at: datetime = Model.field(Model.DateTimeInsert)


    User.insert  # VariantStructSchema[UserInsert]

Pyright cannot compute a variant's keys from the fields (no mapped types),
so each variant's Type is declared: ``Model.Class[Insert, Update, Json,
JsonCreate, JsonUpdate]``, each defaulting to ``Mapping[str, object]``.
When the class is made, a TypedDict given there must have exactly the
variant's keys, and only keys with a constructor default may be
``NotRequired`` (``TypeError`` otherwise). A subclass keeps its base's
TypedDicts and is checked against them too, so it adds fields only to the
variants they leave untyped.
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import (
    Any,
    Generic,
    Literal,
    Self,
    TypeVar,
    cast,
    dataclass_transform,
    get_args,
    get_origin,
    is_typeddict,
    overload,
)

from pyfect.schema._class import field as schema_field
from pyfect.schema._derive import optional_keys
from pyfect.schema._schema import Codec
from pyfect.schema.model._toolkit import TOOLKIT, Variant
from pyfect.schema.variant_schema import Class as VariantClass
from pyfect.schema.variant_schema import (
    Field,
    HasVariants,
    Struct,
    VariantAttribute,
    VariantStructSchema,
    WithConstructorDefault,
    field,
)

type _TD = Mapping[str, object]

In = TypeVar("In", bound=_TD, default=Mapping[str, object])
U = TypeVar("U", bound=_TD, default=Mapping[str, object])
J = TypeVar("J", bound=_TD, default=Mapping[str, object])
JC = TypeVar("JC", bound=_TD, default=Mapping[str, object])
JU = TypeVar("JU", bound=_TD, default=Mapping[str, object])
A_co = TypeVar("A_co", covariant=True)
I_co = TypeVar("I_co", covariant=True)
U_co = TypeVar("U_co", covariant=True)

_TYPED: tuple[Variant, ...] = ("insert", "update", "json", "json_create", "json_update")


@dataclass(frozen=True, slots=True)
class ModelVariants(Generic[A_co, I_co, U_co]):
    """What ``sql.model`` reads from a model class: its ``select`` Type and
    its insert / update variants' Types (``Class.__model_variants__``)."""

    model: Codec[A_co, Any, Any, Any]
    insert: VariantStructSchema[Any]
    update: VariantStructSchema[Any]


class _Select:
    def __get__(self, instance: object, owner: type[VariantClass]) -> VariantStructSchema[_TD]:
        return _attribute("select", owner)


class _Insert:
    def __get__[X: _TD](
        self, instance: object, owner: type[Class[X, Any, Any, Any, Any]]
    ) -> VariantStructSchema[X]:
        return _attribute("insert", owner)


class _Update:
    def __get__[X: _TD](
        self, instance: object, owner: type[Class[Any, X, Any, Any, Any]]
    ) -> VariantStructSchema[X]:
        return _attribute("update", owner)


class _Json:
    def __get__[X: _TD](
        self, instance: object, owner: type[Class[Any, Any, X, Any, Any]]
    ) -> VariantStructSchema[X]:
        return _attribute("json", owner)


class _JsonCreate:
    def __get__[X: _TD](
        self, instance: object, owner: type[Class[Any, Any, Any, X, Any]]
    ) -> VariantStructSchema[X]:
        return _attribute("json_create", owner)


class _JsonUpdate:
    def __get__[X: _TD](
        self, instance: object, owner: type[Class[Any, Any, Any, Any, X]]
    ) -> VariantStructSchema[X]:
        return _attribute("json_update", owner)


_ATTRIBUTES = {variant: VariantAttribute(variant) for variant in ("select", *_TYPED)}


def _attribute(variant: str, owner: type[VariantClass]) -> Any:
    return _ATTRIBUTES[variant].__get__(None, owner)


@dataclass_transform(
    kw_only_default=True, frozen_default=True, field_specifiers=(field, schema_field)
)
class Class(VariantClass, Generic[In, U, J, JC, JU]):
    """A model (Effect's ``Model.Class``): the class is the ``select``
    variant; ``insert``, ``update``, ``json``, ``json_create`` and
    ``json_update`` are the other variants' struct schemas (``select`` is
    the ``select`` variant as a struct). See ``pyfect.schema.model``."""

    __variant_set__ = TOOLKIT

    select = _Select()
    insert = _Insert()
    update = _Update()
    json = _Json()
    json_create = _JsonCreate()
    json_update = _JsonUpdate()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for variant, typed_dict in zip(_TYPED, _variant_args(cls), strict=False):
            if is_typeddict(typed_dict):
                _check_typed_dict(cls, variant, typed_dict)

    @classmethod
    def __model_variants__(cls) -> ModelVariants[Self, In, U]:
        return ModelVariants(cls, cls.insert, cls.update)


def _variant_args(cls: type) -> tuple[object, ...]:
    """The ``Model.Class[...]`` arguments ``cls`` has, its own or inherited
    (a subclass keeps its base's variant types, so they must fit it too)."""
    for klass in cls.__mro__:
        for base in klass.__dict__.get("__orig_bases__", ()):
            if get_origin(base) is Class:
                return get_args(base)
    return ()


def _check_typed_dict(cls: type[VariantClass], variant: str, typed_dict: Any) -> None:
    """``typed_dict`` has the keys of ``variant``, ``NotRequired`` only for
    keys with a constructor default."""
    present: dict[str, bool] = {}
    merged: dict[str, object] = {}
    for klass in reversed(cls.__mro__):
        merged.update(klass.__dict__.get("_variant_own", {}))
    for name, value in merged.items():
        if isinstance(value, Field):
            schema = cast("Field[Any]", value).schemas.get(variant)
            if schema is not None:
                present[name] = isinstance(schema, WithConstructorDefault)
        else:
            present[name] = isinstance(value, WithConstructorDefault)
    declared = cast("frozenset[str]", typed_dict.__required_keys__ | typed_dict.__optional_keys__)
    optional = optional_keys(typed_dict)
    problems = [
        *(f"missing key {k!r}" for k in present if k not in declared),
        *(f"unknown key {k!r}" for k in sorted(declared) if k not in present),
        *(
            f"key {k!r} is NotRequired but has no constructor default"
            for k in sorted(optional)
            if k in present and not present[k]
        ),
    ]
    if problems:
        raise TypeError(
            f"{cls.__name__}: {typed_dict.__name__} is not its {variant!r} variant: "
            + ", ".join(problems)
        )


@overload
def extract[C: VariantClass](self: type[C], variant: Literal["select"], /) -> type[C]: ...
@overload
def extract[X: _TD](
    self: type[Class[X, Any, Any, Any, Any]], variant: Literal["insert"], /
) -> VariantStructSchema[X]: ...
@overload
def extract[X: _TD](
    self: type[Class[Any, X, Any, Any, Any]], variant: Literal["update"], /
) -> VariantStructSchema[X]: ...
@overload
def extract[X: _TD](
    self: type[Class[Any, Any, X, Any, Any]], variant: Literal["json"], /
) -> VariantStructSchema[X]: ...
@overload
def extract[X: _TD](
    self: type[Class[Any, Any, Any, X, Any]], variant: Literal["json_create"], /
) -> VariantStructSchema[X]: ...
@overload
def extract[X: _TD](
    self: type[Class[Any, Any, Any, Any, X]], variant: Literal["json_update"], /
) -> VariantStructSchema[X]: ...
@overload
def extract(self: Struct, variant: Variant, /) -> VariantStructSchema[_TD]: ...
def extract(self: HasVariants, variant: Variant, /) -> Any:
    """``variant``'s struct schema of a model or a model struct (Effect's
    ``Model.extract``); a model's ``select`` variant is the class itself."""
    return TOOLKIT.extract(self, variant)


def fields(self: HasVariants, /) -> Mapping[str, object]:
    """The field definitions of a model or a model struct (Effect's
    ``Model.fields``)."""
    return self.__variant_fields__()


__all__ = ["Class", "ModelVariants", "extract", "fields"]
