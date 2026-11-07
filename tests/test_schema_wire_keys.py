"""A schema class's keys are what goes on the wire, so each must be the one
Effect's class has: camelCase, through ``S.field(key=)``."""

from typing import Any

import pytest
from _pyfect_modules import modules

from pyfect import schema as S

_SHAPE = "__pyfect_schema_shape__"


def _schema_classes() -> list[type]:
    found: set[type] = set()
    for imported in modules(skip_missing_extras=True):
        for value in vars(imported).values():
            if isinstance(value, type) and hasattr(value, _SHAPE):
                found.add(value)
    return sorted(found, key=lambda c: f"{c.__module__}.{c.__qualname__}")


def test_every_key_of_a_schema_class_is_effects_camel_case() -> None:
    snake = [
        f"{cls.__module__}.{cls.__qualname__}.{key}"
        for cls in _schema_classes()
        for key in getattr(cls, _SHAPE).keys.values()
        if "_" in key
    ]
    assert snake == []


def test_two_fields_cannot_share_a_key() -> None:
    def define() -> type:
        class Twice(S.Class):
            a: str = S.field(S.String, key="x")
            b: str = S.field(S.String, key="x")

        return Twice

    with pytest.raises(TypeError, match="two fields one key"):
        define()


def test_a_field_cannot_take_another_fields_name_as_its_key() -> None:
    def define() -> type:
        class Taken(S.Class):
            x: str
            b: str = S.field(S.String, key="x")

        return Taken

    with pytest.raises(TypeError, match="two fields one key"):
        define()


def test_a_tagged_class_cannot_give_a_field_its_tag_key() -> None:
    def define() -> type:
        class Tagged(S.TaggedClass, tag="T"):
            a: str = S.field(S.String, key="_tag")

        return Tagged

    with pytest.raises(TypeError, match="two fields one key"):
        define()


def test_a_default_and_a_subclass_keep_the_key() -> None:
    class _Base(S.Class):
        first_name: str = S.field(S.String, key="firstName", default="n")

    class _Child(_Base):
        last_name: str = S.field(S.String, key="lastName", default="l")

    value: Any = _Child()
    assert S.encode_sync(_Child)(value) == {"firstName": "n", "lastName": "l"}
    assert S.decode_unknown_sync(_Child)({"lastName": "x"}) == _Child(last_name="x")
