"""Ports of Effect's ``schema/VariantSchema.test.ts`` (the ``VariantSchema``
and ``Model`` blocks). Each test's docstring is the Effect test title,
prefixed by its ``describe`` block.

Python mappings: ``Test.Class<User>("User")({...})`` is ``class
User(Test.Class)`` with annotated fields (a field given by a variant field
through ``VS.field(...)``); ``extend`` is subclassing; a variant is read
with ``Test.extract(User, "b")`` (Effect's ``User.b`` exists at run time
too, untyped); ``Object.keys(schema.fields)`` is ``list(schema.fields)``
and a class's ``User.fields`` is ``User.fields()``. ``new User({...})`` is
the keyword constructor and ``User.make`` takes an instance. ``undefined``
in a field map is ``None``. ``Model.Override`` is ``Model.override``.
"""

from datetime import datetime
from typing import TypedDict

import pytest

from pyfect import date_time, testing
from pyfect import schema as S
from pyfect.schema import model as Model
from pyfect.schema import variant_schema as VS

# --- VariantSchema ---------------------------------------------------------------


def test_field_only_and_field_except_select_fields_from_key_arrays():
    """VariantSchema / FieldOnly and FieldExcept select fields from key arrays"""
    test = VS.make(variants=["a", "b", "c"], default_variant="a")
    struct = test.Struct(
        {
            "common": S.String,
            "onlyB": test.field_only(["b"])(S.Number),
            "exceptC": test.field_except(["c"])(S.Boolean),
        }
    )
    assert list(test.extract(struct, "a").fields) == ["common", "exceptC"]
    assert list(test.extract(struct, "b").fields) == ["common", "onlyB", "exceptC"]
    assert list(test.extract(struct, "c").fields) == ["common"]


def test_class_preserves_class_and_variant_schema_behavior():
    """VariantSchema / Class preserves class and variant schema behavior"""
    test = VS.make(variants=["a", "b"], default_variant="a")

    class User(test.Class):
        id: float = VS.field(test.field_only(["a"])(S.Number))
        name: str

    user = User.make(User(id=1, name="Alice"))
    assert isinstance(user, User)
    assert user == User(id=1, name="Alice")
    assert S.decode_sync(User)({"id": 1, "name": "Alice"}) == user
    assert S.decode_sync(test.extract(User, "b"))({"name": "Alice"}) == {"name": "Alice"}
    assert list(User.fields()) == ["id", "name"]


def test_includes_plain_variant_structs_in_the_default_union():
    """VariantSchema / includes plain variant structs in the default union"""
    test = VS.make(variants=["a", "b"], default_variant="a")
    first = test.Struct({"value": S.String})
    second = test.Struct({"value": S.Number})
    union = test.Union([first, second])
    assert len(union.members) == 2
    assert S.decode_unknown_sync(union)({"value": "foo"}) == {"value": "foo"}
    assert S.decode_unknown_sync(union)({"value": 42}) == {"value": 42}


def test_omits_undefined_fields_accepted_by_variant_schema_struct():
    """VariantSchema / omits undefined fields accepted by VariantSchema.Struct"""
    test = VS.make(variants=["a"], default_variant="a")
    struct = test.Struct({"value": S.String, "skipped": None})
    assert list(test.extract(struct, "a").fields) == ["value"]


def test_omits_undefined_fields_selected_by_variant_schema_field():
    """VariantSchema / omits undefined fields selected by VariantSchema.Field"""
    test = VS.make(variants=["a"], default_variant="a")
    struct = test.Struct({"value": S.String, "skipped": test.Field(a=None)})
    assert list(test.extract(struct, "a").fields) == ["value"]


def test_does_not_collide_the_default_variant_with_the_default_schema_cache_entry():
    """VariantSchema / does not collide the __default variant with the default-schema cache entry"""
    test = VS.make(variants=["a", "__default"], default_variant="a")
    variants = {"a": S.String, "__default": S.Number}
    default_first = test.Struct({"value": test.Field(**variants)})
    test.extract(default_first, "a")
    assert test.extract(default_first, "__default").fields["value"] is S.Number

    named_first = test.Struct({"value": test.Field(**variants)})
    test.extract(named_first, "__default")
    assert test.extract(named_first, "a").fields["value"] is S.String


# --- Model -----------------------------------------------------------------------


def test_preserves_classes_when_extracting_the_default_variant():
    """Model / preserves classes when extracting the default variant"""

    class Person(Model.Class):
        name: str

    person = S.decode_sync(Model.extract(Person, "select"))({"name": "Alex"})
    assert isinstance(person, Person)


def test_class_extend_preserves_inherited_members_and_variants():
    """Model / Class.extend preserves inherited members and variants"""

    class Person(Model.Class):
        id: float = Model.field(Model.GeneratedByDb(S.Number))
        name: str

        @property
        def upper_name(self) -> str:
            return self.name.upper()

    assert S.is_schema(Person)
    Model.extract(Person, "json")

    class PersonWithPosts(Person, identifier="PersonWithPosts"):
        posts: tuple[str, ...] = Model.field(
            Model.field_only(["select", "json"])(S.Array(S.String))
        )

    person = S.decode_sync(PersonWithPosts)({"id": 1, "name": "Alex", "posts": ["Hello"]})
    assert isinstance(person, PersonWithPosts)
    assert isinstance(person, Person)
    assert person.upper_name == "ALEX"
    assert person.posts == ("Hello",)
    assert list(PersonWithPosts.select.fields) == ["id", "name", "posts"]
    assert list(PersonWithPosts.insert.fields) == ["name"]
    assert list(Model.extract(PersonWithPosts, "json").fields) == ["id", "name", "posts"]
    decoded = S.decode_sync(PersonWithPosts.json)({"id": 1, "name": "Alex", "posts": []})
    assert decoded == {"id": 1, "name": "Alex", "posts": ()}


def test_field_option_preserves_omitted_variants():
    """Model / FieldOption preserves omitted variants"""
    field = Model.FieldOption(Model.Field(select=S.String, json=None))
    assert field.schemas.get("json") is None


def test_field_only_includes_fields_only_in_listed_variants():
    """Model / FieldOnly includes fields only in listed variants"""
    insert_only = Model.Struct({"value": Model.field_only(["insert"])(S.String)})
    assert list(Model.extract(insert_only, "insert").fields) == ["value"]
    assert list(Model.extract(insert_only, "select").fields) == []


def test_boolean_sqlite_encodes_database_bits_and_json_booleans_across_variants():
    """Model / BooleanSqlite encodes database bits and JSON booleans across variants"""
    user = Model.Struct({"active": Model.BooleanSqlite})
    select = Model.extract(user, "select")
    json = Model.extract(user, "json")
    assert S.encode_sync(select)({"active": True}) == {"active": 1}
    assert S.decode_sync(select)({"active": 0}) == {"active": False}
    assert S.encode_sync(json)({"active": True}) == {"active": True}
    assert S.decode_sync(json)({"active": False}) == {"active": False}


@testing.effect
def test_overrideable_defaults_are_constructor_only_and_accept_explicit_overrides():
    """Model / Overrideable defaults are constructor-only and accept explicit overrides"""
    user = Model.Struct({"createdAt": Model.DateTimeInsertFromNumber})
    insert = Model.extract(user, "insert")

    now = yield from date_time.now()
    made = yield from insert.make_effect({})
    assert made["createdAt"] == now

    yield from S.encode_effect(insert)({"createdAt": Model.override(now)})

    error = yield from S.decode_unknown_effect(insert)({}).flip()
    assert "createdAt" in str(error)


def test_overrideable_sync_make_fills_the_default():
    """(pyfect) a variant struct's synchronous make runs the default too"""
    insert = Model.extract(Model.Struct({"created": Model.DateTimeInsert}), "insert")
    made = insert.make({})
    assert isinstance(made["created"], datetime)
    assert insert.make({"created": made["created"]}) == made


def test_an_annotated_field_outside_the_default_variant_is_rejected():
    """(pyfect) a field the select variant lacks cannot be annotated"""
    with pytest.raises(TypeError, match="not in the 'select' variant"):

        class Bad(Model.Class):  # pyright: ignore[reportUnusedClass]
            secret: str = Model.field(Model.field_only(["insert"])(S.String))


def test_a_subclass_of_a_typed_model_keeps_its_variant_typed_dicts():
    """(pyfect) a subclass adding a field to a typed variant is rejected"""

    class PersonInsert(TypedDict):
        name: str

    class Person(Model.Class[PersonInsert]):
        id: int = Model.field(Model.GeneratedByDb(S.Int))
        name: str

    class WithPosts(Person):  # select and json only: PersonInsert still fits
        posts: tuple[str, ...] = Model.field(
            Model.field_only(["select", "json"])(S.Array(S.String))
        )

    assert list(WithPosts.insert.fields) == ["name"]
    with pytest.raises(
        TypeError, match="PersonInsert is not its 'insert' variant: missing key 'age'"
    ):

        class WithAge(Person):  # pyright: ignore[reportUnusedClass]
            age: int
