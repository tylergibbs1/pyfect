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
