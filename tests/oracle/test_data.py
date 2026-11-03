"""Ports of Effect's ``Data.test.ts``.

``Data.Class`` and ``Data.TaggedClass`` are frozen dataclasses (the class is
the tag), ``Data.taggedEnum`` a union of them read with ``match`` and
``isinstance``, and ``Data.Error`` / ``Data.TaggedError`` a dataclass
subclass of ``errors.TaggedError`` (docs/PARITY.md section 4). ``_tag`` is
the class, so "sets _tag" checks ``type(x)``.

Omitted, with the reason:

- the two "supports .pipe()" titles: a dataclass has no ``pipe``; Python
  calls the function on it.
- "copies own enumerable string and symbol keys only" and "keeps the class
  prototype when args has an own __proto__ key": a dataclass constructor
  takes exactly its fields, so there are no extra keys or prototypes to copy.
- "declarations reference the named constructor types": TypeScript
  declaration emit.
- "toJSON includes fields": ``dataclasses.asdict`` is the field dictionary;
  pyfect errors have no ``toJSON``.
"""

import dataclasses
import math
from dataclasses import dataclass

import pyfect as fx
from pyfect import testing
from pyfect.errors import TaggedError


@dataclass(frozen=True)
class Person:
    name: str
    age: int


def test_class_assigns_fields_from_constructor_args() -> None:
    """assigns fields from constructor args"""
    p = Person(name="Alice", age=30)
    assert (p.name, p.age) == ("Alice", 30)


def test_class_structural_equality() -> None:
    """structural equality via Equal.equals"""
    assert Person(name="Bob", age=25) == Person(name="Bob", age=25)
    assert hash(Person(name="Bob", age=25)) == hash(Person(name="Bob", age=25))


def test_class_not_equal_when_fields_differ() -> None:
    """not equal when fields differ"""
    assert Person(name="Bob", age=25) != Person(name="Bob", age=26)


def test_class_without_fields() -> None:
    """allows classes without fields to be constructed without args"""

    @dataclass(frozen=True)
    class Empty:
        pass

    assert isinstance(Empty(), Empty)


def test_class_fields_are_enumerable() -> None:
    """fields are enumerable"""
    assert sorted(f.name for f in dataclasses.fields(Person(name="D", age=2))) == ["age", "name"]


@dataclass(frozen=True)
class Foo:
    value: int


def test_tagged_class_sets_tag() -> None:
    """sets _tag to the provided tag"""
    assert type(Foo(1)) is Foo


def test_tagged_class_assigns_fields() -> None:
    """TaggedClass: assigns fields"""
    assert Foo(42).value == 42


def test_tagged_class_structural_equality_includes_tag() -> None:
    """structural equality includes _tag"""
    assert Foo(1) == Foo(1)


def test_tagged_class_different_tags_are_not_equal() -> None:
    """different tags are not equal"""

    @dataclass(frozen=True)
    class Bar:
        value: int

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


def test_tagged_enum_creates_a_variant() -> None:
    """creates a variant with _tag"""
    c = Circle(radius=5)
    assert type(c) is Circle
    assert c.radius == 5


def test_tagged_enum_creates_different_variants() -> None:
    """creates different variants"""
    r = Rect(width=3, height=4)
    assert type(r) is Rect
    assert (r.width, r.height) == (3, 4)


def test_tagged_enum_is_matching_variant() -> None:
    """returns true for matching variant"""
    assert isinstance(Circle(1), Circle)


def test_tagged_enum_is_non_matching_variant() -> None:
    """returns false for non-matching variant"""
    shape: Shape = Rect(1, 1)
    assert not isinstance(shape, Circle)


def test_tagged_enum_is_non_tagged_values() -> None:
    """returns false for non-tagged values"""
    values: list[object] = [None, "string", {}]
    for value in values:
        assert not isinstance(value, Circle)


def test_tagged_enum_match_circle() -> None:
    """data-last: matches Circle"""
    assert area(Circle(5)) == math.pi * 25


def test_tagged_enum_match_rect() -> None:
    """data-last: matches Rect"""
    assert area(Rect(3, 4)) == 12


def test_tagged_enum_match_directly() -> None:
    """data-first: matches directly"""

    def double_radius(shape: Shape) -> float:
        match shape:
            case Circle(radius):
                return radius * 2
            case Rect():
                return 0

    assert double_radius(Circle(1)) == 2


@dataclass(frozen=True)
class Nothing:
    pass


@dataclass(frozen=True)
class Just:
    value: int


def test_tagged_enum_accepts_void_for_empty_variants() -> None:
    """accepts void for empty variants"""
    assert type(Nothing()) is Nothing


def test_tagged_enum_match_for_empty_variants() -> None:
    """works with $match for empty variants"""

    def show(o: Nothing | Just) -> str:
        match o:
            case Nothing():
                return "none"
            case Just(value):
                return f"some({value})"

    assert show(Nothing()) == "none"
    assert show(Just(42)) == "some(42)"


@dataclass(frozen=True, eq=False)
class MyError(TaggedError):
    code: int
    message: str


def test_error_is_an_instance_of_error() -> None:
    """Error: is an instance of globalThis.Error"""
    assert isinstance(MyError(code=500, message="fail"), Exception)


def test_error_assigns_fields() -> None:
    """Error: assigns fields"""
    e = MyError(code=404, message="not found")
    assert (e.code, e.message, str(e)) == (404, "not found", "not found")


def test_error_has_a_stack_trace() -> None:
    """has a stack trace (once raised, as any Python exception)"""
    try:
        raise MyError(code=1, message="x")
    except MyError as e:
        assert e.__traceback__ is not None


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


def test_tagged_error_sets_tag() -> None:
    """sets _tag"""
    assert type(NotFound(resource="/x")) is NotFound


def test_tagged_error_assigns_fields() -> None:
    """TaggedError: assigns fields"""
    assert NotFound(resource="/users").resource == "/users"


def test_tagged_error_is_an_instance_of_error() -> None:
    """TaggedError: is an instance of globalThis.Error"""
    assert isinstance(NotFound(resource="r"), Exception)


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


def test_tagged_error_name_is_the_tag() -> None:
    """sets .name to the tag"""
    assert type(NotFound(resource="x")).__name__ == "NotFound"


def test_tagged_error_different_tags_are_not_equal() -> None:
    """different tags produce non-equal errors"""

    @dataclass(frozen=True, eq=False)
    class Forbidden(TaggedError):
        resource: str

    assert NotFound(resource="x") != Forbidden(resource="x")
    assert NotFound(resource="x") == NotFound(resource="x")
