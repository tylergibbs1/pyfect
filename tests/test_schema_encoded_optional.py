"""A key or tuple element that a decoding default fills is optional on the
encoded side, so the representation and the JSON Schema of that side say
so (Effect reads ``isOptional(getLastEncoding(...))``). Expected values
printed by Effect 4.0.6 under Node."""

from typing import Any, TypedDict

from pyfect import effect as fx
from pyfect import schema as S
from pyfect.schema import representation as R


class _Fields(TypedDict):
    a: str
    b: Any


def _schema() -> S.Top:
    return S.Struct(
        _Fields,
        a=S.String.pipe(S.with_decoding_default_key(fx.succeed("x"))),
        b=S.Tuple(S.String.pipe(S.with_decoding_default_key(fx.succeed("y")))),
    )


def test_the_representation_marks_defaulted_positions_optional():
    assert R.to_json(R.to_representation(_schema())) == {
        "representation": {
            "_tag": "Objects",
            "checks": [],
            "propertySignatures": [
                {
                    "name": {"type": "string", "value": "a"},
                    "type": {"_tag": "String", "checks": []},
                    "isOptional": True,
                    "isMutable": False,
                },
                {
                    "name": {"type": "string", "value": "b"},
                    "type": {
                        "_tag": "Arrays",
                        "checks": [],
                        "elements": [
                            {"isOptional": True, "type": {"_tag": "String", "checks": []}}
                        ],
                        "rest": [],
                    },
                    "isOptional": False,
                    "isMutable": False,
                },
            ],
            "indexSignatures": [],
        },
        "references": {},
    }


def test_the_json_schema_does_not_require_defaulted_positions():
    assert S.to_json_schema_document(_schema()).schema == {
        "type": "object",
        "properties": {
            "a": {"type": "string"},
            "b": {"type": "array", "prefixItems": [{"type": "string"}], "maxItems": 1},
        },
        "required": ["b"],
        "additionalProperties": True,
    }


def test_the_type_side_keeps_defaulted_positions_required():
    objects = R.to_representation(S.to_type(_schema())).representation
    assert isinstance(objects, R.Objects)
    a, b = objects.property_signatures
    assert not a.is_optional
    assert isinstance(b.type, R.Arrays)
    assert not b.type.elements[0].is_optional
