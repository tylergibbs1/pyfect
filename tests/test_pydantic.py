"""``pyfect.pydantic``: pyfect schemas as pydantic field types, and pydantic
models as pyfect schemas."""

from datetime import timedelta
from typing import Annotated

import pytest

pydantic = pytest.importorskip("pydantic")

from pydantic import BaseModel, ValidationError  # noqa: E402

from pyfect import pydantic as P  # noqa: E402
from pyfect import schema as S  # noqa: E402
from pyfect.result import Err  # noqa: E402


class User(S.Class):
    name: str
    age: int = S.field(S.Int)


class Order(BaseModel):
    total: Annotated[float, S.FiniteFromString]
    wait: Annotated[timedelta, S.Duration]
    user: User


def _order() -> Order:
    return Order.model_validate(
        {"total": "1.5", "wait": timedelta(seconds=1), "user": {"name": "a", "age": 3}}
    )


def test_python_input_is_decoded_with_the_schema():
    order = _order()

    assert order.total == 1.5
    assert order.user == User(name="a", age=3)


def test_values_the_decoded_side_accepts_are_kept():
    order = Order(total=2.0, wait=timedelta(0), user=User(name="b", age=1))

    assert (order.total, order.user) == (2.0, User(name="b", age=1))


def test_dumping_encodes_with_the_schema_and_json_with_its_json_codec():
    order = _order()

    assert order.model_dump() == {
        "total": "1.5",
        "wait": timedelta(seconds=1),
        "user": {"name": "a", "age": 3},
    }
    text = order.model_dump_json()
    assert text == (
        '{"total":"1.5","wait":{"_tag":"Millis","value":1000},"user":{"name":"a","age":3}}'
    )
    assert Order.model_validate_json(text) == order


def test_a_failure_is_one_pydantic_error_with_the_pyfect_message():
    with pytest.raises(ValidationError) as info:
        Order.model_validate({"total": "x", "wait": timedelta(0), "user": {"name": 1, "age": 1}})

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
        "age": {"type": "integer"},
    }


class Item(BaseModel):
    sku: str
    qty: int


def test_from_model_decodes_with_the_model_and_encodes_its_json_dump():
    schema = P.from_model(Item)

    assert S.decode_unknown_sync(schema)({"sku": "a", "qty": "2"}) == Item(sku="a", qty=2)
    assert S.encode_sync(schema)(Item(sku="a", qty=2)) == {"sku": "a", "qty": 2}


def test_from_model_reports_each_pydantic_error_at_its_location():
    result = S.decode_unknown_result(S.Array(P.from_model(Item)))(
        [{"sku": "a", "qty": 1}, {"qty": "x"}]
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
