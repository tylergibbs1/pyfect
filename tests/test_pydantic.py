"""``pyfect.pydantic``: pyfect schemas as pydantic field types, and pydantic
models as pyfect schemas."""

from typing import Annotated, Any, Never

import pytest

pydantic = pytest.importorskip("pydantic")

from pydantic import BaseModel, ValidationError  # noqa: E402

from pyfect import duration  # noqa: E402
from pyfect import pydantic as P  # noqa: E402
from pyfect import schema as S  # noqa: E402
from pyfect.result import Err  # noqa: E402


class User(S.Class):
    name: str
    age: int = S.field(S.Int)


class Order(BaseModel):
    total: Annotated[float, S.FiniteFromString]
    wait: Annotated[duration.Duration, S.Duration]
    user: User


def _order() -> Order:
    return Order.model_validate(
        {"total": "1.5", "wait": duration.seconds(1), "user": {"name": "a", "age": 3}}
    )


def test_python_input_is_decoded_with_the_schema():
    order = _order()

    assert order.total == 1.5
    assert order.user == User(name="a", age=3)


def test_values_the_decoded_side_accepts_are_kept():
    order = Order(total=2.0, wait=duration.zero, user=User(name="b", age=1))

    assert (order.total, order.user) == (2.0, User(name="b", age=1))


def test_dumping_encodes_with_the_schema_and_json_with_its_json_codec():
    order = _order()

    assert order.model_dump() == {
        "total": "1.5",
        "wait": duration.seconds(1),
        "user": {"name": "a", "age": 3},
    }
    text = order.model_dump_json()
    assert text == (
        '{"total":"1.5","wait":{"_tag":"Millis","value":1000},"user":{"name":"a","age":3}}'
    )
    assert Order.model_validate_json(text) == order


def test_a_failure_is_one_pydantic_error_with_the_pyfect_message():
    with pytest.raises(ValidationError) as info:
        Order.model_validate({"total": "x", "wait": duration.zero, "user": {"name": 1, "age": 1}})

    errors = [(e["loc"], e["msg"], e["type"]) for e in info.value.errors()]
    assert errors == [
        (("total",), "Expected a finite number", "pyfect_schema"),
        (("user",), 'Expected string\n  at ["name"]', "pyfect_schema"),
    ]


def test_the_json_schema_is_the_schemas_with_definitions_inlined():
    properties = Order.model_json_schema()["properties"]

    assert properties["total"] == {"title": "Total", "type": "string"}
    assert properties["user"]["properties"] == {
        "name": {"type": "string"},
        "age": {"type": "integer", "minimum": -(2**53 - 1), "maximum": 2**53 - 1},
    }


class Item(BaseModel):
    sku: str
    qty: int


def test_from_model_decodes_with_the_model_and_encodes_its_json_dump():
    schema = P.from_model(Item)

    assert S.decode_unknown_sync(schema)({"sku": "a", "qty": "2"}) == Item(sku="a", qty=2)
    assert S.encode_sync(schema)(Item(sku="a", qty=2)) == {"sku": "a", "qty": 2}


def test_from_model_stops_at_the_first_pydantic_error_by_default():
    """``errors="first"``, the default, reports one issue, as every schema does."""
    result = S.decode_unknown_result(S.Array(P.from_model(Item)))(
        [{"sku": "a", "qty": 1}, {"qty": "x"}]
    )

    assert isinstance(result, Err)
    assert str(result.error) == 'Missing key\n  at [1]["sku"]'


def test_from_model_reports_each_pydantic_error_at_its_location():
    result = S.decode_unknown_result(S.Array(P.from_model(Item)))(
        [{"sku": "a", "qty": 1}, {"qty": "x"}], errors="all"
    )

    assert isinstance(result, Err)
    assert str(result.error) == (
        'Missing key\n  at [1]["sku"]\n'
        "Input should be a valid integer, unable to parse string as an integer\n"
        '  at [1]["qty"]'
    )


class Person(S.Class):
    name: str
    friend: "Person | None" = None


class Team(BaseModel):
    lead: Person


def test_a_self_referring_schema_class_is_a_field_type():
    team = Team.model_validate({"lead": {"name": "a", "friend": {"name": "b"}}})

    assert team.lead == Person(name="a", friend=Person(name="b"))
    assert Team.model_validate_json(team.model_dump_json()) == team


class _Inner(BaseModel):
    model_config = pydantic.ConfigDict(revalidate_instances="always")
    s: Annotated[str, S.StringFromBase64]
    h: Annotated[str, S.StringFromHex]


class _Outer(BaseModel):
    inner: _Inner


def test_revalidating_an_instance_keeps_its_decoded_values():
    inner = _Inner(s=b"\xff".decode("latin-1"), h="3132")
    revalidated = _Outer(inner=inner).inner
    assert (revalidated.s, revalidated.h) == (inner.s, inner.h)


def test_assigning_a_decoded_value_keeps_it():
    class Assigned(BaseModel):
        model_config = pydantic.ConfigDict(validate_assignment=True)
        n: Annotated[float, S.NumberFromString]

    model = Assigned(n="1.5")  # pyright: ignore[reportArgumentType]
    model.n = 2.0
    assert model.n == 2.0
    model.n = "3.5"  # pyright: ignore[reportAttributeAccessIssue]
    assert model.n == 3.5


def _codecs() -> list[tuple[str, S.Codec[Any, Any, Never, Never]]]:
    return [
        (name, value)
        for name in dir(S)
        if isinstance(value := getattr(S, name), S.Bottom) and value.__codec__().ast.encoding
    ]


@pytest.mark.parametrize(("name", "schema"), _codecs())
def test_python_validation_is_idempotent_for_every_catalog_codec(
    name: str, schema: S.Codec[Any, Any, Never, Never]
):
    """The guard: pydantic validates a value again on revalidation and
    assignment, so validating a validated value must give it back."""
    from hypothesis import HealthCheck, given, settings

    try:
        strategy = S.to_strategy(schema)
    except (TypeError, ValueError):
        pytest.skip(f"{name} has no strategy")
    adapter = pydantic.TypeAdapter(Annotated[object, schema])
    encode = S.encode_sync(schema)

    @settings(
        max_examples=30,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
        database=None,
    )
    @given(strategy)
    def check(value: object) -> None:
        once = adapter.validate_python(encode(value))
        assert S.to_equivalence(schema)(adapter.validate_python(once), once)

    check()
