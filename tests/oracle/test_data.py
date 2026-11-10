"""Ports of Effect's ``Data.test.ts``.

``Data.Class`` and ``Data.TaggedClass`` are frozen dataclasses (the class is
the tag), ``Data.taggedEnum`` a union of them read with ``match`` and
``isinstance``, and ``Data.Error`` / ``Data.TaggedError`` a dataclass
subclass of ``errors.TaggedError`` (docs/PARITY.md section 4). ``_tag`` is
the class, so "sets _tag" checks ``type(x)``.

Omitted, with the reason:

- the two "supports .pipe()" titles: a dataclass has no ``pipe``; Python
  calls the function on it.
- "keeps the class prototype when args has an own __proto__ key": a
  dataclass constructor takes exactly its fields, so there is no prototype
  to copy.
- "declarations reference the named constructor types": TypeScript
  declaration emit.
- "toJSON includes fields": ``dataclasses.asdict`` is the field dictionary;
  pyfect errors have no ``toJSON``.
"""

import dataclasses
import math
from dataclasses import dataclass

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.errors import TaggedError


@dataclass(frozen=True)
class Person:
    name: str
    age: int


def test_class_compares_instances_structurally() -> None:
    """compares instances structurally"""
    a = Person(name="Bob", age=25)
    assert a == Person(name="Bob", age=25)
    assert hash(a) == hash(Person(name="Bob", age=25))
    assert a != Person(name="Bob", age=26)


def test_class_copies_own_fields_only() -> None:
    """copies own enumerable string and symbol keys only, as enumerable fields

    A dataclass takes exactly its fields: they are its attributes, in order, and an
    extra key is refused rather than copied."""
    p = Person(name="E", age=3)
    assert (p.name, p.age) == ("E", 3)
    assert [f.name for f in dataclasses.fields(p)] == ["name", "age"]
    with pytest.raises(TypeError):
        Person(name="E", age=3, hidden=1)  # pyright: ignore[reportCallIssue]


def test_class_without_fields() -> None:
    """allows classes without fields to be constructed without args"""

    @dataclass(frozen=True)
    class Empty:
        pass

    assert isinstance(Empty(), Empty)


@dataclass(frozen=True)
class Foo:
    value: int


def test_tagged_class_sets_tag_and_assigns_fields() -> None:
    """sets _tag to the provided tag and assigns fields"""
    f = Foo(42)
    assert type(f) is Foo
    assert f.value == 42


def test_tagged_class_compares_structurally_including_tag() -> None:
    """compares instances structurally, including _tag"""

    @dataclass(frozen=True)
    class Bar:
        value: int

    assert Foo(1) == Foo(1)
    assert Foo(1) != Bar(1)


def test_tagged_class_without_fields() -> None:
    """allows tagged classes without fields to be constructed without args"""

    @dataclass(frozen=True)
    class Empty:
        pass

    assert type(Empty()) is Empty


@dataclass(frozen=True)
class Circle:
    radius: float


@dataclass(frozen=True)
class Rect:
    width: float
    height: float


type Shape = Circle | Rect


def area(shape: Shape) -> float:
    match shape:
        case Circle(radius):
            return math.pi * radius**2
        case Rect(width, height):
            return width * height


def test_tagged_enum_constructors() -> None:
    """constructors create tagged variants"""
    c = Circle(radius=5)
    assert (type(c), c.radius) == (Circle, 5)
    r = Rect(width=3, height=4)
    assert (type(r), r.width, r.height) == (Rect, 3, 4)


def test_tagged_enum_is() -> None:
    """$is only accepts values with the named tag"""
    values: list[object] = [Circle(1), Rect(1, 1), None, "string", {}]
    assert [isinstance(value, Circle) for value in values] == [True, False, False, False, False]


def test_tagged_enum_match() -> None:
    """$match dispatches on _tag, data-last and data-first"""

    def measure(shape: Shape) -> float:
        match shape:
            case Circle(radius):
                return radius * 2
            case Rect(width, height):
                return width * height

    assert measure(Circle(5)) == 10
    assert measure(Rect(3, 4)) == 12
    assert measure(Circle(1)) == 2
    assert measure(Rect(2, 5)) == 10
    assert area(Circle(5)) == math.pi * 25


@dataclass(frozen=True)
class Nothing:
    pass


@dataclass(frozen=True)
class Just:
    value: int


def test_tagged_enum_variants_without_fields() -> None:
    """constructs and matches variants without fields"""

    def show(o: Nothing | Just) -> str:
        match o:
            case Nothing():
                return "none"
            case Just(value):
                return f"some({value})"

    assert type(Nothing()) is Nothing
    assert show(Nothing()) == "none"
    assert show(Just(42)) == "some(42)"


@dataclass(frozen=True, eq=False)
class MyError(TaggedError):
    code: int
    message: str


def test_error_with_stack_trace_and_fields() -> None:
    """is a globalThis.Error with a stack trace and the provided fields

    The stack trace is there once raised, as for any Python exception."""
    e = MyError(code=404, message="not found")
    assert isinstance(e, Exception)
    assert (e.code, e.message, str(e)) == (404, "not found", "not found")
    try:
        raise e
    except MyError as raised:
        assert raised.__traceback__ is not None


def test_error_without_fields() -> None:
    """allows errors without fields to be constructed without args"""

    @dataclass(frozen=True, eq=False)
    class Empty(TaggedError):
        pass

    assert isinstance(Empty(), Exception)


@testing.effect
def test_error_can_be_yielded_to_fail():
    """can be yielded in Effect.gen to fail"""

    @fx.gen
    def failing():
        yield from MyError(code=1, message="boom")

    exit_ = yield from failing.exit()
    assert exit_ == fx.exit.fail(MyError(code=1, message="boom"))


@dataclass(frozen=True, eq=False)
class NotFound(TaggedError):
    resource: str


def test_tagged_error_named_after_tag_with_fields() -> None:
    """is a globalThis.Error named after its _tag, with the provided fields"""
    e = NotFound(resource="/users")
    assert isinstance(e, Exception)
    assert type(e) is NotFound
    assert type(e).__name__ == "NotFound"
    assert e.resource == "/users"


@testing.effect
def test_tagged_error_can_be_caught_with_catch_tag():
    """can be caught with Effect.catchTag"""

    @fx.gen
    def failing():
        yield from NotFound(resource="/test")
        return ""

    result = yield from failing.pipe(
        fx.catch_tag(NotFound, lambda e: fx.succeed(f"caught: {e.resource}"))
    )
    assert result == "caught: /test"


def test_tagged_error_without_fields() -> None:
    """allows tagged errors without fields to be constructed without args"""

    @dataclass(frozen=True, eq=False)
    class Boom(TaggedError):
        pass

    e = Boom()
    assert type(e) is Boom
    assert isinstance(e, Exception)


def test_tagged_error_different_tags_are_not_equal() -> None:
    """different tags produce non-equal errors"""

    @dataclass(frozen=True, eq=False)
    class Forbidden(TaggedError):
        resource: str

    assert NotFound(resource="x") != Forbidden(resource="x")
    assert NotFound(resource="x") == NotFound(resource="x")
