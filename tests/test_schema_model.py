"""``pyfect.schema.model`` beyond the ``Model.test.ts`` ports: the check of a
model's variant TypedDicts (a pyfect-only part, docs/PARITY.md section 4)."""

import re
from collections.abc import Mapping
from datetime import datetime
from typing import TypedDict

import pytest

from pyfect import schema as S
from pyfect.schema import model as Model


def test_a_variant_typed_dict_mismatch_lists_the_keys_the_variant_has():
    # DOGFOOD B2: the message named the wrong keys but not the right ones.
    class MonitorUpdate(TypedDict):
        id: int
        url: str
        created_at: datetime

    expected = (
        "Monitor: MonitorUpdate is not its 'update' variant: "
        "missing key 'updated_at', unknown key 'created_at', unknown key 'id'; "
        "the 'update' variant has keys: 'url', 'updated_at' (may be NotRequired)"
    )
    with pytest.raises(TypeError, match=re.escape(expected)):

        class Monitor(Model.Class[Mapping[str, object], MonitorUpdate]):  # pyright: ignore[reportUnusedClass]
            id: int = Model.field(Model.GeneratedByDb(S.Int))
            url: str
            created_at: datetime = Model.field(Model.DateTimeInsert)
            updated_at: datetime = Model.field(Model.DateTimeUpdate)


def test_a_field_outside_select_wrapped_in_model_field_names_the_fix():
    # Dogfood audit (models.mdx): it died with dataclasses' "is a field but has
    # no type annotation".
    expected = (
        "Broken.extra is not in the 'select' variant: assign the variant field without field(...)"
    )
    with pytest.raises(TypeError, match=re.escape(expected)):

        class Broken(Model.Class):  # pyright: ignore[reportUnusedClass]
            body: str
            extra = Model.field(Model.Field(json=S.String))  # pyright: ignore[reportGeneralTypeIssues]


def test_an_unannotated_model_field_in_select_asks_for_the_annotation():
    expected = "Broken.extra is in the 'select' variant: annotate it with its type"
    with pytest.raises(TypeError, match=re.escape(expected)):

        class Broken(Model.Class):  # pyright: ignore[reportUnusedClass]
            extra = Model.field(Model.Sensitive(S.String))  # pyright: ignore[reportGeneralTypeIssues]
