"""Schema classes (Effect's ``Schema.Class``, ``TaggedClass``, ``Error``,
``TaggedError``): a dataclass that is also its own schema::

    class User(S.Class):
        id: int
        name: str
        score: float = S.field(S.Finite)
        nick: str | None = None

    S.decode_unknown_sync(User)({"id": 1, "name": "a", "score": 2})

Each annotation is a field's Type and, unless ``S.field`` gives another
schema, stands for its schema (see ``pyfect.schema._derive``), derived on
first use so a class may refer to itself or to classes defined after it.
A default makes the key optional when decoding. The constructor checks
every field against its schema's Type and runs the ``@S.class_check``
methods, raising ``SchemaError``; decoding builds the instance from the
decoded fields without checking them twice.

Instances are frozen dataclasses with keyword-only fields and structural
equality (``frozen=False`` in the class line makes them mutable).
Subclassing extends: a subclass has its base's fields, checks and tag.
``TaggedClass`` / ``TaggedError`` add a ``"_tag"`` key holding the class's
tag (``tag=``, by default the class name); ``Error`` / ``TaggedError``
are ``pyfect.errors.TaggedError`` subclasses, so ``catch_tag`` takes them.
"""

from __future__ import annotations

import dataclasses
import functools
import inspect
import sys
import types
from collections.abc import Callable, Mapping
from dataclasses import MISSING, FrozenInstanceError
from typing import (
    Any,
    ClassVar,
    LiteralString,
    NamedTuple,
    Never,
    Self,
    Unpack,
    cast,
    dataclass_transform,
    get_type_hints,
    overload,
)

from pyfect import errors
from pyfect._core import Effect
from pyfect.exit import Success
from pyfect.option import Option
from pyfect.schema import ast
from pyfect.schema._adapters import CONSTRUCTOR, raise_schema_failure
from pyfect.schema._constructor_default import tag as tag_schema
from pyfect.schema._derive import AnyBottom, schema_of
from pyfect.schema._error import SchemaError
from pyfect.schema._exact import Exact
from pyfect.schema._make import make_class_sync
from pyfect.schema._options import ParseOptions
from pyfect.schema._schema import Bottom, Codec
from pyfect.schema._undefined import is_undefined
from pyfect.schema.ast import Check, FilterOutput, filter_of
from pyfect.schema.issue import Issue

_SCHEMA = "pyfect.schema"
"""The ``dataclasses.Field.metadata`` key of a field's explicit schema."""


@overload
def field[A](schema: Codec[A, object, Never, Never], /, *, key: str | None = None) -> A: ...
@overload
def field[A](schema: Exact[A, Never, Never], /, *, default: A, key: str | None = None) -> A: ...
@overload
def field[A](
    schema: Codec[A, object, Never, Never],
    /,
    *,
    default_factory: Callable[[], A],
    key: str | None = None,
) -> A: ...
@overload
def field[A](*, default_factory: Callable[[], A], key: str | None = None) -> A: ...
@overload
def field[A](*, default: A, key: str) -> A: ...
@overload
def field(*, key: str) -> Any: ...
def field(
    schema: Codec[object, object, Never, Never] | Exact[Any, Never, Never] | None = None,
    /,
    *,
    default: object = MISSING,
    default_factory: Callable[[], object] | None = None,
    key: str | None = None,
) -> Any:
    """A schema class field: ``schema`` instead of the annotation's (its
    Type must fit the annotation), a default or a default factory, and
    ``key``, its name in the class's schema where that is not the attribute's:
    what it encodes to, decodes from and is called in decode issues, and what a
    mapping given to ``make`` holds it under. The constructor keeps the
    attribute's name."""
    metadata: dict[str, object] = {}
    if schema is not None:
        metadata[_SCHEMA] = schema
    if key is not None:
        metadata[_KEY] = key
    if default_factory is not None:
        return dataclasses.field(default_factory=default_factory, metadata=metadata)
    return dataclasses.field(default=default, metadata=metadata)


_KEY = "__pyfect_class_key__"
"""The ``dataclasses.field`` metadata naming a field's key in the schema."""

_CHECK = "__pyfect_class_check__"
"""The attribute holding a ``class_check`` method's filter."""


def class_check[F: Callable[[Any], FilterOutput]](
    *, abort: bool = False, **annotations: object
) -> Callable[[F], F]:
    """Mark a method of a schema class as a check of its instances (Effect's
    checks on a class's struct): it returns a ``FilterOutput`` (``True`` /
    ``None`` to accept, ``False``, a message, an issue, ...) and runs after
    the fields are valid, when constructing and when decoding.
    ``expected=`` / ``message=`` annotate the failure; ``abort=True`` stops
    the checks after it when it fails. Subclasses inherit the checks."""

    def mark(method: F) -> F:
        setattr(method, _CHECK, filter_of(method, annotations or None, abort))
        return method

    return mark


class _Built(NamedTuple):
    """What a schema class's first use derives from its fields."""

    schemas: dict[str, AnyBottom]
    """By attribute."""
    fields: ast.Objects
    """The decoding struct, by key."""
    constructor: ast.AST
    """The fields' Types by attribute: issues of ``Class(...)`` name its keywords."""
    encoded: ast.AST
    absent_when_none: frozenset[str]


def _is_undefined_or(node: ast.AST) -> bool:
    return isinstance(node, ast.Union) and any(is_undefined(m) for m in node.types)


def _defaults_to_none(cls: type, name: str) -> bool:
    return next(f for f in dataclasses.fields(cast("Any", cls)) if f.name == name).default is None


class _Shape:
    """A schema class's schema: its fields' struct, made on first use."""

    __slots__ = (
        "_built",
        "checks",
        "cls",
        "codec",
        "field_names",
        "identifier",
        "init",
        "keys",
        "name",
        "tag",
    )

    def __init__(
        self,
        cls: type[object],
        identifier: str,
        tag: str | None,
        init: Callable[..., None],
        checks: ast.Checks | None,
        *,
        annotations: Mapping[str, object] | None,
    ) -> None:
        self.cls = cls
        self.identifier = identifier
        self.tag = tag
        self.name = identifier
        """An error's ``name`` (``_ErrorName``)."""
        self.init = init
        self.checks = checks
        fields = [f for f in dataclasses.fields(cast("Any", cls)) if f.init]
        self.field_names = tuple(f.name for f in fields)
        self.keys: Mapping[str, str] = {f.name: f.metadata.get(_KEY, f.name) for f in fields}
        taken = ["_tag"] if tag is not None else []
        for key in self.keys.values():
            if key in taken:
                raise TypeError(f"{cls.__name__} gives two fields one key: {key!r}")
            taken.append(key)
        self.codec = Bottom[Any, Mapping[str, object]](
            ast.Class(self, annotations={"identifier": identifier, **(annotations or {})})
        )
        self._built: _Built | None = None

    def _build(self) -> _Built:
        if self._built is None:
            schemas = _field_schemas(self.cls, self.field_names)
            defaults = {name: _default_of(self.cls, name) for name in schemas}
            absent = frozenset(
                self.keys[name]
                for name, schema in schemas.items()
                if _defaults_to_none(self.cls, name) and _is_undefined_or(schema.ast)
            )
            keyed = tuple(
                ast.PropertySignature(
                    self.keys[name], schema.ast, self.keys[name] in absent, defaults[name]
                )
                for name, schema in schemas.items()
            )
            named = tuple(
                ast.PropertySignature(name, schema.ast, default=defaults[name])
                for name, schema in schemas.items()
            )
            if self.tag is not None:
                # Effect's ``tag``: ``make`` from plain fields fills it in.
                tag = ast.PropertySignature("_tag", tag_schema(cast("LiteralString", self.tag)).ast)
                keyed, named = (tag, *keyed), (tag, *named)
            # As Effect's ``extend``: a subclass's fields carry its identifier.
            extends = any(_SHAPE in base.__dict__ for base in self.cls.__mro__[1:])
            fields = ast.Objects(
                keyed, annotations={"identifier": self.identifier} if extends else None
            )
            self._built = _Built(
                schemas, fields, ast.Objects(named).to_type(), fields.flip().to_type(), absent
            )
        return self._built

    @property
    def schemas(self) -> dict[str, AnyBottom]:
        return self._build().schemas

    @property
    def fields(self) -> ast.Objects:
        return self._build().fields

    @property
    def encoded(self) -> ast.AST:
        return self._build().encoded

    def construct(self, values: dict[object, object]) -> object:
        instance = self.cls.__new__(self.cls)
        keys = self.keys
        self.init(
            instance,
            **{name: values[keys[name]] for name in self.field_names if keys[name] in values},
        )
        return instance

    def values_of(self, instance: object) -> dict[object, object]:
        """Keyed as the schema is; a field that is Effect's ``Schema.optional``
        (``undefined`` allowed, ``None`` the default) has no key while ``None``,
        as Effect's has none while it is absent. A dataclass cannot tell an
        absent field from an explicit ``None``."""
        values: dict[object, object] = {} if self.tag is None else {"_tag": self.tag}
        absent = self._build().absent_when_none
        keys = self.keys
        for name in self.field_names:
            value = getattr(instance, name)
            if value is not None or keys[name] not in absent:
                values[keys[name]] = value
        return values

    def validate(self, instance: object) -> None:
        """Raise ``SchemaError`` unless ``instance``'s fields fit their
        schemas' Types and the class's checks pass."""
        values: dict[object, object] = {} if self.tag is None else {"_tag": self.tag}
        for name in self.field_names:
            values[name] = getattr(instance, name)
        match ast.run_now(self._build().constructor.parse(values, {})):
            case Success():
                pass
            case failure:
                raise_schema_failure(failure.cause.map(SchemaError), CONSTRUCTOR)
        match ast.check_instance(self, instance, {}):
            case Success():
                pass
            case failure:
                raise_schema_failure(failure.cause.map(SchemaError), CONSTRUCTOR)


_SHAPE = "__pyfect_schema_shape__"
"""The class attribute holding a schema class's ``_Shape`` (in its own
``__dict__``: a subclass has its own)."""


def _shape_of(cls: type) -> _Shape:
    shape = cls.__dict__.get(_SHAPE)
    if not isinstance(shape, _Shape):
        raise TypeError(f"{cls.__name__} is a schema class base: subclass it to make a schema")
    return shape


def _field_schemas(cls: type, names: tuple[str, ...]) -> dict[str, AnyBottom]:
    """Each field's schema: the one ``S.field`` gives, else its annotation's,
    evaluated in the module of the class that declares it."""
    declared = {f.name: f for f in dataclasses.fields(cast("Any", cls))}
    schemas: dict[str, AnyBottom] = {}
    for name in names:
        explicit = declared[name].metadata.get(_SCHEMA)
        schemas[name] = (
            cast("Codec[Any, Any, Any, Any]", explicit).__codec__()
            if explicit is not None
            else schema_of(_annotation(cls, name))
        )
    return schemas


def _annotation(cls: type, name: str) -> object:
    owner = next(k for k in cls.__mro__ if name in inspect.get_annotations(k))
    module = sys.modules.get(owner.__module__)
    holder = types.SimpleNamespace(
        __annotations__={name: inspect.get_annotations(owner)[name]},
        __globals__=vars(module) if module is not None else {},
    )
    return get_type_hints(holder, localns=dict(vars(owner)))[name]


def _default_of(cls: type, name: str) -> Callable[[], object] | None:
    f = next(f for f in dataclasses.fields(cast("Any", cls)) if f.name == name)
    if f.default is not MISSING:
        value = f.default
        return lambda: value
    if f.default_factory is not MISSING:
        return f.default_factory
    return None


def _checks_of(cls: type) -> ast.Checks | None:
    """The ``@class_check`` methods of ``cls`` and its bases, bases first; a
    method overriding a base's replaces its check."""
    found: dict[str, ast.Filter[Any]] = {}
    for klass in reversed(cls.__mro__):
        for name, value in vars(klass).items():
            check = getattr(value, _CHECK, None)
            if isinstance(check, ast.Filter):
                found.pop(name, None)
                found[name] = cast("ast.Filter[Any]", check)
            elif name in found:
                del found[name]
    checks = tuple(found.values())
    return (checks[0], *checks[1:]) if checks else None


def _define(
    cls: type,
    *,
    identifier: str | None,
    tag: str | None,
    frozen: bool,
    error: bool,
    annotations: Mapping[str, object] | None,
) -> None:
    """Make ``cls`` a dataclass whose constructor validates, and its schema."""
    own_ast_field = "ast" in inspect.get_annotations(cls) and "ast" not in cls.__dict__
    if own_ast_field:
        # ``@dataclass`` reads a field's default with ``getattr(cls, name)``,
        # which would give the class's ``ast``.
        type.__setattr__(cls, "ast", MISSING)
    # Errors keep pyfect.errors.TaggedError's structural equality and hash.
    dataclasses.dataclass(cls, kw_only=True, frozen=frozen, eq=not error)
    if own_ast_field:
        type.__delattr__(cls, "ast")
    if error and frozen:
        # A frozen dataclass rejects every attribute, ``__traceback__`` and
        # ``__notes__`` included; only the fields are frozen here.
        type.__setattr__(cls, "__setattr__", _error_setattr)
        type.__setattr__(cls, "__delattr__", _error_delattr)
    init = _linking_cause(cls.__dict__["__init__"]) if error else cls.__dict__["__init__"]
    shape = _Shape(
        cls, identifier or cls.__name__, tag, init, _checks_of(cls), annotations=annotations
    )
    if error:
        shape.name = identifier if identifier is not None else tag or cls.__name__
    type.__setattr__(cls, _SHAPE, shape)

    @functools.wraps(init)
    def __init__(self: object, *args: object, **kwargs: object) -> None:
        init(self, *args, **kwargs)
        shape.validate(self)

    type.__setattr__(cls, "__init__", __init__)
    if tag is not None:
        type.__setattr__(cls, "_tag", tag)


def _error_setattr(self: errors.TaggedError, name: str, value: object) -> None:
    if name in _shape_of(type(self)).field_names:
        raise FrozenInstanceError(f"cannot assign to field {name!r}")
    errors.TaggedError.__setattr__(self, name, value)


def _error_delattr(self: errors.TaggedError, name: str) -> None:
    if name in _shape_of(type(self)).field_names:
        raise FrozenInstanceError(f"cannot delete field {name!r}")
    object.__delattr__(self, name)


def _linking_cause(init: Callable[..., None]) -> Callable[..., None]:
    """``init`` then a ``cause`` field holding an exception made the
    ``__cause__`` (a frozen dataclass sets fields past ``__setattr__``).
    Both construction and decoding build errors through it."""

    def linked(self: BaseException, *args: object, **kwargs: object) -> None:
        init(self, *args, **kwargs)
        cause = self.__dict__.get("cause")
        if isinstance(cause, BaseException) and self.__cause__ is not cause:
            self.__cause__ = cause

    return linked


def _tag_for(cls: type, tag: str | None) -> str:
    """``tag``, else the tag ``cls`` inherits, else its name."""
    if tag is not None:
        return tag
    inherited = getattr(cls, "_tag", None)
    return inherited if isinstance(inherited, str) else cls.__name__


class _ClassAst:
    """``A.ast``, the class's schema node, as every Effect schema has. Read
    on the class only (an instance has none); a field called ``ast`` is the
    instance's (``_define`` keeps ``@dataclass`` from taking this for its
    default)."""

    def __get__(self, obj: None, owner: type, /) -> ast.AST:
        if obj is not None:
            raise AttributeError("ast")
        return cast("Codec[object, object, object, object]", owner).__codec__().ast


class _SchemaClass:
    """What every schema class has: it is a schema (``Codec``) of itself."""

    ast = _ClassAst()

    @classmethod
    def __codec__(cls) -> Bottom[Self, Mapping[str, object]]:
        return _shape_of(cls).codec

    @classmethod
    def __get_pydantic_core_schema__(cls, source: object, handler: object) -> object:
        """The class as a pydantic field type (``pyfect.pydantic``)."""
        return cls.__codec__().__get_pydantic_core_schema__(source, handler)

    @classmethod
    def __get_pydantic_json_schema__(cls, core: object, handler: object) -> object:
        return cls.__codec__().__get_pydantic_json_schema__(core, handler)

    @classmethod
    def fields(cls) -> Mapping[str, Bottom[object, object, Never, Never]]:
        """Each field's schema, the tag's first in a tagged class."""
        shape = _shape_of(cls)
        schemas = shape.schemas
        if shape.tag is None:
            return dict(schemas)
        tag: Bottom[object, object, Never, Never] = Bottom(ast.Literal(shape.tag))
        return {"_tag": tag, **schemas}

    @classmethod
    def make(cls, input: Self, /, **options: Unpack[ParseOptions]) -> Self:
        """``input`` checked against the class's schema (its checks
        included); raises ``SchemaError``. Construct with ``cls(...)``; an
        instance is kept as it is."""
        shape = _shape_of(cls)
        return make_class_sync(
            cls.ast.to_type(),
            input,
            options,
            lambda fields: cast("Self", shape.construct(dict(fields))),
        )

    @classmethod
    def make_option(cls, input: Self, /, **options: Unpack[ParseOptions]) -> Option[Self]:
        return cls.__codec__().make_option(input, **options)

    @classmethod
    def make_effect(cls, input: Self, /, **options: Unpack[ParseOptions]) -> Effect[Self, Issue]:
        return cls.__codec__().make_effect(input, **options)

    @classmethod
    def annotate(cls, /, **annotations: object) -> Bottom[Self, Mapping[str, object]]:
        """The class's schema with annotations (a new schema, not a class)."""
        return cls.__codec__().annotate(**annotations)

    @classmethod
    def check(cls, first: Check[Self], /, *rest: Check[Self]) -> Bottom[Self, Mapping[str, object]]:
        """The class's schema with checks (a new schema, not a class)."""
        return cls.__codec__().check(first, *rest)

    @classmethod
    def pipe[B](cls, f: Callable[[type[Self]], B], /) -> B:
        return f(cls)


@dataclass_transform(kw_only_default=True, frozen_default=True, field_specifiers=(field,))
class Class(_SchemaClass):
    """A schema class (Effect's ``Schema.Class``); see ``pyfect.schema``.
    ``identifier=`` names it in messages (default: the class name) and
    ``annotations=`` annotate its schema."""

    def __init_subclass__(
        cls,
        *,
        identifier: str | None = None,
        frozen: bool = True,
        annotations: Mapping[str, object] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)
        _define(
            cls,
            identifier=identifier,
            tag=None,
            frozen=frozen,
            error=False,
            annotations=annotations,
        )


@dataclass_transform(kw_only_default=True, frozen_default=True, field_specifiers=(field,))
class TaggedClass(_SchemaClass):
    """A schema class encoded with a ``"_tag"`` key (Effect's
    ``Schema.TaggedClass``): ``tag=`` (default: the inherited tag, else the
    class name), required when decoding and written when encoding."""

    _tag: ClassVar[str]

    def __init_subclass__(
        cls,
        *,
        tag: str | None = None,
        identifier: str | None = None,
        frozen: bool = True,
        annotations: Mapping[str, object] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)
        _define(
            cls,
            identifier=identifier,
            tag=_tag_for(cls, tag),
            frozen=frozen,
            error=False,
            annotations=annotations,
        )


class _ErrorName:
    """``error.name`` (Effect's ``name`` on an error's prototype): the
    class's ``identifier``, else its tag, else its name. A non-data
    descriptor, so a field called ``name`` wins; read on the class it is
    absent, so ``@dataclass`` never takes it for a field's default."""

    @overload
    def __get__(self, obj: None, owner: type, /) -> Never: ...
    @overload
    def __get__(self, obj: object, owner: type | None = None, /) -> str: ...
    def __get__(self, obj: object, owner: type | None = None, /) -> str:
        if obj is None:
            raise AttributeError("name")
        return _shape_of(type(obj)).name


@dataclass_transform(kw_only_default=True, frozen_default=True, field_specifiers=(field,))
class Error(_SchemaClass, errors.TaggedError):
    """A schema class that is a ``pyfect.errors.TaggedError`` (Effect's
    ``Schema.Error``): yieldable, caught by ``catch_tag``, equal by fields;
    a ``message`` field is its text and a ``cause`` field its
    ``__cause__``. ``name`` is its identifier (default: the class name),
    unless it has a field of that name."""

    name = _ErrorName()

    def __init_subclass__(
        cls,
        *,
        identifier: str | None = None,
        frozen: bool = True,
        annotations: Mapping[str, object] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)
        _define(
            cls,
            identifier=identifier,
            tag=None,
            frozen=frozen,
            error=True,
            annotations=annotations,
        )


@dataclass_transform(kw_only_default=True, frozen_default=True, field_specifiers=(field,))
class TaggedError(_SchemaClass, errors.TaggedError):
    """``Error`` encoded with a ``"_tag"`` key, as ``TaggedClass`` (Effect's
    ``Schema.TaggedError``); ``name`` is its identifier, else its tag."""

    name = _ErrorName()

    _tag: ClassVar[str]

    def __init_subclass__(
        cls,
        *,
        tag: str | None = None,
        identifier: str | None = None,
        frozen: bool = True,
        annotations: Mapping[str, object] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)
        _define(
            cls,
            identifier=identifier,
            tag=_tag_for(cls, tag),
            frozen=frozen,
            error=True,
            annotations=annotations,
        )
