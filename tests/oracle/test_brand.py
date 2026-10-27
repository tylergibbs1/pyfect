"""Ports of Effect's ``Brand.test.ts``. Each test's docstring is the Effect
test title. A brand is a ``typing.NewType`` and ``Brand<T>`` is
``Brand[Base, T]``; ``Option`` results are
``Some(value)`` or ``None``.

Every title is ported. Schema (M8) is not ported yet, so ``Schema.isInt()``
and ``Schema.isGreaterThan(0)`` are ``Filter`` values with the same
``expected`` text, and ``String(error)`` (``"BrandError(<message>)"``) is
Python's ``str(error)``, the message.
"""

from typing import NewType

import pytest

from pyfect.brand import Brand, BrandError, Filter
from pyfect.option import Some
from pyfect.result import Err, Ok

Int = NewType("Int", float)
Positive = NewType("Positive", float)
PositiveInt = NewType("PositiveInt", float)
MyNumber = NewType("MyNumber", float)

is_int = Filter[float](lambda n: n.is_integer(), expected="an integer")
is_greater_than_0 = Filter[float](lambda n: n > 0, expected="a value greater than 0")


def assert_success[B](ctor: Brand[float, B], value: float) -> None:
    assert ctor.result(value) == Ok(value)


def assert_failure[B](ctor: Brand[float, B], value: float, message: str) -> None:
    match ctor.result(value):
        case Err(error):
            assert error.message == message
        case Ok():
            pytest.fail(f"{value} passed")


def test_formats_validation_failures_as_brand_error() -> None:
    """formats validation failures as BrandError"""
    to_int = Brand[float, Int].check(is_int)
    result = to_int.result(1.1)
    assert isinstance(result, Err)
    assert isinstance(result.error, BrandError)
    assert str(result.error) == "Expected an integer"


def test_creates_nominal_brands_without_runtime_validation() -> None:
    """creates nominal brands without runtime validation"""
    my_number = Brand[float, MyNumber].nominal()
    for value in (1, 1.1, -1):
        assert my_number(value) == value
        assert my_number.is_(value)
        assert my_number.option(value) == Some(value)
        assert_success(my_number, value)


def test_validates_custom_predicates_created_with_make() -> None:
    """validates custom predicates created with make"""
    to_int = Brand[float, Int].make(lambda n: n.is_integer() or f"Expected {n} to be an integer")
    assert to_int(1) == 1
    with pytest.raises(BrandError):
        to_int(1.1)
    assert to_int(-1) == -1
    assert to_int.is_(1)
    assert not to_int.is_(1.1)
    assert to_int.is_(-1)
    assert to_int.option(1) == Some(1)
    assert to_int.option(1.1) is None
    assert to_int.option(-1) == Some(-1)
    assert_success(to_int, 1)
    assert_failure(to_int, 1.1, "Expected 1.1 to be an integer")
    assert_success(to_int, -1)


def test_validates_a_single_schema_check() -> None:
    """validates a single schema check"""
    to_int = Brand[float, Int].check(is_int)
    assert to_int(1) == 1
    with pytest.raises(BrandError, match=r"^Expected an integer$"):
        to_int(1.1)
    assert to_int(-1) == -1
    assert to_int.is_(1)
    assert not to_int.is_(1.1)
    assert to_int.is_(-1)
    assert to_int.option(1) == Some(1)
    assert to_int.option(1.1) is None
    assert to_int.option(-1) == Some(-1)
    assert_success(to_int, 1)
    assert_failure(to_int, 1.1, "Expected an integer")
    assert_success(to_int, -1)


def test_accumulates_failures_from_multiple_schema_checks() -> None:
    """accumulates failures from multiple schema checks"""
    positive_int = Brand[float, PositiveInt].check(is_int, is_greater_than_0)
    assert_success(positive_int, 1)
    assert_failure(positive_int, 1.1, "Expected an integer")
    assert_failure(positive_int, -1, "Expected a value greater than 0")
    assert_failure(positive_int, -1.1, "Expected an integer\nExpected a value greater than 0")


def test_stops_after_an_aborted_failed_schema_check() -> None:
    """stops after an aborted failed schema check"""
    positive_int = Brand[float, PositiveInt].check(is_int.abort(), is_greater_than_0)
    assert_success(positive_int, 1)
    assert_failure(positive_int, 1.1, "Expected an integer")
    assert_failure(positive_int, -1, "Expected a value greater than 0")
    assert_failure(positive_int, -1.1, "Expected an integer")


def test_combines_existing_brand_constructors_with_all() -> None:
    """combines existing brand constructors with all"""
    to_int = Brand[float, Int].check(is_int)
    positive = Brand[float, Positive].check(is_greater_than_0)
    positive_int = Brand[float, PositiveInt].all(to_int, positive)
    assert positive_int(1) == 1
    with pytest.raises(BrandError):
        positive_int(1.1)
    with pytest.raises(BrandError):
        positive_int(-1)
    assert positive_int.is_(1)
    assert not positive_int.is_(1.1)
    assert not positive_int.is_(-1)
    assert positive_int.option(1) == Some(1)
    assert positive_int.option(1.1) is None
    assert positive_int.option(-1) is None
    assert_success(positive_int, 1)
    assert_failure(positive_int, 1.1, "Expected an integer")
    assert_failure(positive_int, -1.1, "Expected an integer\nExpected a value greater than 0")
