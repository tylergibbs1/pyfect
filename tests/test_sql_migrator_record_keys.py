"""``migrator.from_record`` refuses a key that is not ``<id>_<name>``.

Effect's ``fromRecord`` skips such a key, so the migration never runs and the
first query fails far away (``no such table``). pyfect raises when the loader
is made, naming the key (docs/PARITY.md §4)."""

import pytest

import pyfect as fx
from pyfect.sql import migrator


@pytest.mark.parametrize("key", ["1", "init", "1init", "a_init", "_init", "1_", "٣_init"])
def test_a_key_without_an_id_and_a_name_is_refused_by_name(key: str):
    with pytest.raises(ValueError, match="<id>_<name>") as caught:
        migrator.from_record({"1_ok": fx.void, key: fx.void})
    assert repr(key) in str(caught.value)


def test_well_formed_keys_load_in_id_order():
    loaded = fx.run_sync(migrator.from_record({"10_late": fx.void, "02_early": fx.void}).or_die())
    assert [(id_, name) for id_, name, _ in loaded] == [(2, "early"), (10, "late")]
