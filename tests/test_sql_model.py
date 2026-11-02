"""``pyfect.sql.model`` beyond the ``SqlModel.test.ts`` ports: what a
repository's arguments are checked against, and when."""

import re
from collections.abc import Mapping
from typing import TypedDict

import pytest

from pyfect import schema as S
from pyfect.schema import model as Model
from pyfect.sql import model as sql_model


class CheckUpdate(TypedDict):
    url: str


class Check(Model.Class[Mapping[str, object], CheckUpdate]):
    # The obvious autoincrement key, but GeneratedByDb is in select and json only.
    id: int = Model.field(Model.GeneratedByDb(S.Int))
    url: str


_NOT_IN_UPDATE = (
    "Check: id_column 'id' must be a field of the select and update variants; "
    "the 'update' variant has: 'url' (a GeneratedByDb field is in select and json only: "
    "declare the id with Model.field_only(['select', 'update', 'json'])(...))"
)


def test_make_repository_rejects_an_id_outside_update_when_called():
    # DOGFOOD B4: this failed only when the layer that ran it was built.
    with pytest.raises(ValueError, match=re.escape(_NOT_IN_UPDATE)):
        sql_model.make_repository(Check, table_name="checks", span_prefix="Checks", id_column="id")


def test_make_resolvers_rejects_an_id_outside_update_when_called():
    with pytest.raises(ValueError, match=re.escape(_NOT_IN_UPDATE)):
        sql_model.make_resolvers(Check, table_name="checks", span_prefix="Checks", id_column="id")


def test_make_repository_rejects_an_unknown_soft_delete_column_when_called():
    class Row(Model.Class):
        id: int = Model.field(Model.field_only(["select", "update", "json"])(S.Int))

    with pytest.raises(ValueError, match=re.escape("Row has no 'deleted_at' field")):
        sql_model.make_repository(
            Row,
            table_name="rows",
            span_prefix="Rows",
            id_column="id",
            soft_delete_column="deleted_at",
        )
