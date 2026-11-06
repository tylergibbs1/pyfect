"""``migrator.from_record`` skips a key that is not ``<id>_<name>``, as Effect's
``fromRecord`` does (``flatMapNullishOr`` over its key pattern)."""

import pytest

import pyfect as fx
from pyfect.sql import migrator


@pytest.mark.parametrize("key", ["1", "init", "1init", "a_init", "_init", "1_", "٣_init"])
def test_a_key_without_an_id_and_a_name_is_skipped(key: str):
    loaded = fx.run_blocking(migrator.from_record({"1_ok": fx.void, key: fx.void}).or_die())
    assert [(id_, name) for id_, name, _ in loaded] == [(1, "ok")]


def test_well_formed_keys_load_in_id_order():
    loaded = fx.run_blocking(
        migrator.from_record({"10_late": fx.void, "02_early": fx.void}).or_die()
    )
    assert [(id_, name) for id_, name, _ in loaded] == [(2, "early"), (10, "late")]
