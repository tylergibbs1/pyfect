"""Ports of Effect's ``Schema.test.ts``: ``Class``, ``TaggedClass``,
``Error`` and ``TaggedError``. Each test's docstring is the Effect test
title, prefixed by its ``describe`` block. ``TestSchema.Asserts`` is
``testing.SchemaAsserts``.

Python mappings: ``Schema.Class<A>("A")({...})`` is ``class A(S.Class)``
with annotated fields; ``extend`` is subclassing; ``new A({...})`` is the
keyword constructor ``A(a=...)``, which validates; a struct's checks are
``@S.class_check`` methods; ``withConstructorDefault`` is a field default or
``S.with_constructor_default`` on the field's schema;
``mutableKey`` is ``frozen=False`` on the class line. ``A.make`` takes an
instance (the constructor builds one), so Effect's ``make`` from plain
props is the constructor here.

Ported in part: "Class / make preserves existing instances like the other
constructor adapters" and "Class / Fields argument" (no ``new A(instance)``;
``A.name`` is ``__name__``), the "make with void input" titles (``A()``),
"Class / suspend before initialization" (decoding an instance: an instance
is not a mapping), "Error / fields argument" and "Error / extend" (no
``stack``; ``str(error)`` is pyfect's ``TaggedError`` text, see "Error /
`toString` to match native `Error` output format"), "Error / constructor
ignores excess properties by default" (its cause half).

Omitted:
- Excess keyword arguments raise ``TypeError`` (a Python signature), so
  there is nothing to ignore or strip: "Class / constructor ignores excess
  properties by default", "... strips excess properties with explicit
  ignore", "Class / extend / constructor preserves subclass fields while
  ignoring excess properties by default", "... keeps subclass fields and
  strips excess properties with explicit ignore", "TaggedClass /
  constructor ignores excess properties by default", "Error / constructor
  strips excess properties with explicit ignore", "Error / extended
  constructor ignores excess properties by default", "TaggedError /
  constructor ignores excess properties by default", "TaggedError /
  extended constructor ignores excess properties by default".
- One spelling of a class's fields: "Class / Struct argument", "Error /
  Struct argument" (the "Fields argument" ports cover them), "Class /
  mapFields" (subclass instead).
- ``make`` from plain props (the constructor builds instances): "Class /
  make validates a nested Class source and output once", "Class / make
  constructs nested Class instances with and without Union", "Class / make
  selects the first TaggedClass Union member when the tag is defaulted".
- "Class / make applies constructor defaults only at a field occurrence",
  "Class / Struct with nested Class": ported in
  ``test_schema_constructor_default.py``.
- "Class / should be compatible with `immer` / ...": no immer.
- "TaggedError / name matches tag", "... matches identifier", "...
  matches identifier after extend": a Python exception has no ``name``;
  its class names it.
"""

import traceback
from typing import NotRequired, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect.option import Some
from pyfect.testing import SchemaAsserts

# ------------------------------------------------------------------- Class


def test_class_make_preserves_existing_instances():
    """Class / make preserves existing instances like the other constructor adapters"""
    constructions: list[object] = []

    class A(S.Class):
        a: str

        def __post_init__(self) -> None:
            constructions.append(self)

    instance = A(a="a")
    assert A.make(instance) is instance
    option = A.make_option(instance)
    assert isinstance(option, Some)
    assert option.value is instance
    assert fx.run_blocking(A.make_effect(instance).or_die()) is instance
    assert len(constructions) == 1


class _Row(S.Class):
    value: str


class _DirectTable(S.Class):
    rows: tuple[_Row, ...]


class _UnionTable(S.Class):
    rows: tuple[_Row | None, ...] = S.field(S.Array(S.Union(_Row, S.Null)))


def test_class_make_preserves_class_instances_in_array_class_and_array_union_class():
    """Class / make preserves Class instances in Array(Class) and Array(Union(Class))"""
    row = _Row(value="a")
    assert _DirectTable(rows=(row,)).rows[0] is row
    assert _UnionTable(rows=(row,)).rows[0] is row
    bad: tuple[_Row, ...] = ({"value": 1},)  # pyright: ignore[reportAssignmentType]
    for table in (_DirectTable, _UnionTable):
        with pytest.raises(S.SchemaError):
            table(rows=bad)


def test_class_make_applies_defaults_source_checks_and_the_constructor_once():
    """Class / make applies defaults, source checks, and the constructor once"""
    defaults: list[None] = []
    checks: list[None] = []
    constructions: list[None] = []

    def default() -> str:
        defaults.append(None)
        return "default"

    class A(S.Class):
        a: str = S.field(default_factory=default)

        @S.class_check()
        def counted(self) -> bool:
            checks.append(None)
            return True

        def __post_init__(self) -> None:
            constructions.append(None)

    instance = A()
    assert isinstance(instance, A)
    assert instance.a == "default"
    assert (len(defaults), len(checks), len(constructions)) == (1, 1, 1)


def test_class_make_with_void_input():
    """Class / make with void input"""

    class A(S.Class):
        pass

    assert A.make(A()) == A()
    assert A.make_option(A()) == Some(A())
    assert fx.run_blocking(A.make_effect(A()).or_die()) == A()


def test_class_decoding_validates_the_class_struct_once():
    """Class / decoding validates the class struct once"""
    checks: list[None] = []

    class A(S.Class):
        a: str

        @S.class_check()
        def counted(self) -> bool:
            checks.append(None)
            return True

    instance = S.decode_unknown_sync(A)({"a": "a"})
    assert isinstance(instance, A)
    assert len(checks) == 1


def test_class_make_validates_an_existing_nested_class_once():
    """Class / make validates an existing nested Class once"""
    checks: list[None] = []

    class A(S.Class):
        a: str

    def counted(_: A) -> bool:
        checks.append(None)
        return True

    class Holder(TypedDict):
        a: A

    schema = S.Struct(Holder, a=A.check(S.make_filter(counted)))
    instance = A.make(A(a="a"))
    assert schema.make({"a": instance})["a"] is instance
    assert len(checks) == 1


def test_class_make_allows_an_optional_nested_class_to_be_omitted():
    """Class / make allows an optional nested Class to be omitted"""

    class A(S.Class):
        a: str

    class Holder(TypedDict):
        a: NotRequired[A]

    assert S.Struct(Holder).make({}) == {}


def test_class_suspend_before_initialization():
    """Class / suspend before initialization"""

    class A(S.Class):
        a: str = S.field(S.suspend(lambda: string))

    string = S.String
    asserts = SchemaAsserts(A)
    asserts.make().succeed(A(a="a"))
    asserts.decoding().succeed({"a": "a"}, A(a="a"))


def test_class_should_memoize_the_ast():
    """Class / should memoize the ast"""

    class A(S.Class):
        a: str

    assert A.__codec__().ast is A.__codec__().ast


def test_class_should_set_the_identifier_annotation():
    """Class / should set the identifier annotation"""

    class A(S.Class):
        a: str

    assert (A.__codec__().ast.annotations or {}).get("identifier") == "A"


def test_class_class_with_nested_class():
    """Class / Class with nested Class"""

    class A(S.Class):
        a: str

    class B(S.Class):
        a: A = A(a="default")

    make = SchemaAsserts(B).make()
    make.succeed(B(a=A(a="a")))
    assert B() == B(a=A(a="default"))


def test_class_should_be_possible_to_define_a_class_with_a_mutable_field():
    """Class / should be possible to define a class with a mutable field"""

    class A(S.Class, frozen=False):
        a: str

        def update(self) -> None:
            self.a = "b"

    make = SchemaAsserts(A).make()
    make.succeed(A(a="a"))
    a = A(a="a")
    a.update()
    assert a.a == "b"


def test_class_fields_argument():
    """Class / Fields argument"""

    class A(S.Class):
        a: str

        @property
        def _a(self) -> int:
            return 1

    asserts = SchemaAsserts(A)

    # should be a schema
    assert S.is_schema(A)
    # should expose the fields
    assert A.fields() == {"a": S.String}
    # should expose the identifier
    assert S.resolve_annotations(A) == {"identifier": "A"}
    assert A.__name__ == "A"

    assert isinstance(A(a="a"), A)
    assert isinstance(A.make(A(a="a")), A)

    # test additional fields
    assert A(a="a")._a == 1  # pyright: ignore[reportPrivateUsage]

    # test Equal.equals
    assert A(a="a") == A(a="a")
    assert A(a="a") != A(a="b")

    asserts.make().succeed(A(a="a"))

    decoding = asserts.decoding()
    decoding.succeed({"a": "a"}, A(a="a"))
    decoding.fail(None, "Expected object")
    decoding.fail({"a": 1}, 'Expected string\n  at ["a"]')

    encoding = asserts.encoding()
    encoding.succeed(A(a="a"), {"a": "a"})
    encoding.fail(None, "Expected A")
    encoding.fail({"a": "a"}, "Expected A")


def test_class_constructor_rejects_excess_properties_when_requested():
    """Class / constructor rejects excess properties when requested"""

    class A(S.Class):
        a: str

    with pytest.raises(TypeError):
        A(a="a", extra="extra")  # pyright: ignore[reportCallIssue]


def test_class_annotate():
    """Class / annotate"""

    class A(S.Class):
        a: str

    annotated = A.annotate()
    # should be a schema
    assert S.is_schema(annotated)
    assert isinstance(annotated.make(A(a="a")), A)


def test_class_extend_basic():
    """Class / extend / basic"""

    class A(S.Class):
        a: str

    class B(A):
        b: float

    asserts = SchemaAsserts(B)
    instance = B(a="a", b=2)
    assert isinstance(instance, A)
    assert isinstance(instance, B)
    assert isinstance(B.make(B(a="a", b=2)), B)
    assert (instance.a, instance.b) == ("a", 2)

    asserts.make().succeed(B(a="a", b=2))
    asserts.decoding().succeed({"a": "a", "b": 2}, B(a="a", b=2))


def test_class_extend_decoding_validates_the_extended_struct_once():
    """Class / extend / decoding validates the extended struct once"""
    base_checks: list[None] = []
    extension_checks: list[None] = []

    class A(S.Class):
        a: str

        @S.class_check()
        def base(self) -> bool:
            base_checks.append(None)
            return True

    class B(A):
        b: float

        @S.class_check()
        def extension(self) -> bool:
            extension_checks.append(None)
            return True

    instance = S.decode_unknown_sync(B)({"a": "a", "b": 1})
    assert isinstance(instance, B)
    assert (len(base_checks), len(extension_checks)) == (1, 1)


def test_class_extend_constructor_does_not_treat_subclass_fields_as_excess_properties():
    """Class / extend / constructor does not treat subclass fields as excess properties"""

    class A(S.Class):
        a: str

    class B(A):
        b: float

    instance = B(a="a", b=2)
    assert (instance.a, instance.b) == ("a", 2)
    with pytest.raises(TypeError):
        B(a="a", b=2, extra="extra")  # pyright: ignore[reportCallIssue]


def test_class_extend_struct_argument():
    """Class / extend / Struct argument"""

    class A(S.Class):
        a: float

        @S.class_check(expected="positive a")
        def positive_a(self) -> bool:
            return self.a > 0

    class B(A):
        b: float

        @S.class_check(expected="positive b")
        def positive_b(self) -> bool:
            return self.b > 0

    assert B(a=1, b=1) == B(a=1, b=1)
    with pytest.raises(S.SchemaError, match=r"^Expected positive a$"):
        B(a=0, b=1)
    with pytest.raises(S.SchemaError, match=r"^Expected positive b$"):
        B(a=1, b=0)


def test_class_extend_static_members():
    """Class / extend / static members"""

    class A(S.Class):
        a: str
        a_static = "value"

    class B(A):
        b: float

    assert B.a_static == "value"


# ------------------------------------------------------------- TaggedClass


def test_tagged_class_make_with_void_input():
    """TaggedClass / make with void input"""

    class A(S.TaggedClass):
        pass

    assert A.make(A()) == A()
    assert A.make_option(A()) == Some(A())
    assert fx.run_blocking(A.make_effect(A()).or_die()) == A()


def test_tagged_class_explicit_identifier():
    """TaggedClass / explicit identifier"""

    class A(S.TaggedClass, tag="A", identifier="B"):
        a: str

    assert S.resolve_annotations(A) == {"identifier": "B"}
    assert A._tag == "A"  # pyright: ignore[reportPrivateUsage]


def test_tagged_class_fields_argument():
    """TaggedClass / fields argument"""

    class A(S.TaggedClass):
        a: str

    asserts = SchemaAsserts(A)
    assert S.is_schema(A)
    assert sorted(A.fields()) == ["_tag", "a"]
    assert S.resolve_annotations(A) == {"identifier": "A"}

    instance = A(a="a")
    assert instance._tag == "A"  # pyright: ignore[reportPrivateUsage]
    assert instance.a == "a"

    asserts.make().succeed(A(a="a"))
    asserts.decoding().succeed({"_tag": "A", "a": "a"}, A(a="a"))
    asserts.encoding().succeed(A(a="a"), {"_tag": "A", "a": "a"})


def test_tagged_class_struct_argument():
    """TaggedClass / Struct argument"""

    class A(S.TaggedClass):
        a: str

        @S.class_check(expected='"a" being longer than 0')
        def non_empty(self) -> bool:
            return len(self.a) > 0

    asserts = SchemaAsserts(A)
    assert A(a="a") == A(a="a")
    with pytest.raises(S.SchemaError, match=r'^Expected "a" being longer than 0$'):
        A(a="")

    decoding = asserts.decoding()
    decoding.succeed({"_tag": "A", "a": "a"}, A(a="a"))
    decoding.fail({"a": "a"}, 'Missing key\n  at ["_tag"]')
    decoding.fail({"_tag": "A", "a": ""}, 'Expected "a" being longer than 0')


def test_tagged_class_extended_constructor_does_not_treat_subclass_fields_as_excess():
    """TaggedClass / extended constructor does not treat subclass fields as excess properties"""

    class A(S.TaggedClass):
        a: str

    class B(A):
        b: float

    instance = B(a="a", b=2)
    assert instance._tag == "A"  # pyright: ignore[reportPrivateUsage]
    assert (instance.a, instance.b) == ("a", 2)
    with pytest.raises(TypeError):
        B(a="a", b=2, extra="extra")  # pyright: ignore[reportCallIssue]


# ------------------------------------------------------------------- Error


def test_error_make_with_void_input():
    """Error / make with void input"""

    class E(S.Error):
        pass

    assert E.make(E()) == E()
    assert E.make_option(E()) == Some(E())
    assert fx.run_blocking(E.make_effect(E()).or_die()) == E()


def test_error_fields_argument():
    """Error / fields argument"""

    class E(S.Error):
        id: float

    error = E(id=1)
    assert error.id == 1
    make = SchemaAsserts(E).make()
    make.succeed(E(id=1))


def test_error_constructor_ignores_excess_properties_by_default():
    """Error / constructor ignores excess properties by default"""

    class E(S.Error):
        message: str
        cause: object = None
        code: float

    cause = ValueError("cause")
    error = E(message="boom", cause=cause, code=1)
    assert (error.message, error.cause, error.code) == ("boom", cause, 1)
    assert error.__cause__ is cause


def test_error_extend():
    """Error / extend"""

    class A(S.Error):
        a: str

    class B(A):
        b: float

    asserts = SchemaAsserts(B)
    instance = B(a="a", b=2)
    assert isinstance(instance, A)
    assert isinstance(instance, B)
    assert (instance.a, instance.b) == ("a", 2)
    asserts.make().succeed(B(a="a", b=2))
    asserts.decoding().succeed({"a": "a", "b": 2}, B(a="a", b=2))


def test_error_extended_constructor_does_not_treat_subclass_fields_as_excess():
    """Error / extended constructor does not treat subclass fields as excess properties"""

    class A(S.Error):
        message: str

    class B(A):
        code: float

    error = B(message="boom", code=1)
    assert (error.message, error.code) == ("boom", 1)


def test_error_to_string_matches_native_error_output():
    """Error / `toString` to match native `Error` output format"""

    class E(S.Error):
        message: str

    error = E(message="my message")
    assert str(error) == "my message"
    assert traceback.format_exception_only(error)[-1].endswith("E: my message\n")


# ------------------------------------------------------------- TaggedError


def test_tagged_error_make_preserves_existing_instances():
    """TaggedError / make preserves existing instances"""

    class E(S.TaggedError):
        message: str

    instance = E(message="failure")
    assert E.make(instance) is instance


def test_tagged_error_make_with_void_input():
    """TaggedError / make with void input"""

    class E(S.TaggedError):
        pass

    assert E.make(E()) == E()
    assert E.make_option(E()) == Some(E())
    assert fx.run_blocking(E.make_effect(E()).or_die()) == E()


def test_tagged_error_fields_argument():
    """TaggedError / fields argument"""

    class E(S.TaggedError):
        id: float

    asserts = SchemaAsserts(E)
    error = E(id=1)
    assert error._tag == "E"  # pyright: ignore[reportPrivateUsage]
    assert error.id == 1

    asserts.make().succeed(E(id=1))
    asserts.decoding().succeed({"_tag": "E", "id": 1}, E(id=1))
    asserts.encoding().succeed(E(id=1), {"_tag": "E", "id": 1})


def test_tagged_error_struct_argument():
    """TaggedError / Struct argument"""

    class E(S.TaggedError):
        id: float

    error = E(id=1)
    assert error._tag == "E"  # pyright: ignore[reportPrivateUsage]
    assert error.id == 1
    assert sorted(E.fields()) == ["_tag", "id"]


def test_tagged_error_zero_field_tagged_error_allows_omitting_props_argument():
    """TaggedError / zero-field TaggedError allows omitting props argument"""

    class NotFoundError(S.TaggedError):
        pass

    error = NotFoundError()
    assert error._tag == "NotFoundError"  # pyright: ignore[reportPrivateUsage]
    assert isinstance(error, NotFoundError)


def test_tagged_error_extend():
    """TaggedError / extend"""

    class A(S.TaggedError):
        a: str

    class B(A):
        b: float

    instance = B(a="a", b=2)
    assert instance._tag == "A"  # pyright: ignore[reportPrivateUsage]
    assert isinstance(instance, A)
    assert isinstance(instance, B)


def test_tagged_error_extended_constructor_does_not_treat_subclass_fields_as_excess():
    """TaggedError / extended constructor does not treat subclass fields as excess properties"""

    class A(S.TaggedError):
        a: str

    class B(A):
        b: float

    instance = B(a="a", b=2)
    assert instance._tag == "A"  # pyright: ignore[reportPrivateUsage]
    assert (instance.a, instance.b) == ("a", 2)
