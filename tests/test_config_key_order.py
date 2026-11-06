"""Record keys keep the order the source gave them, as Effect's providers
do (a JavaScript ``Set`` of ``Object.keys``): decoded records list their
keys in that order, and the first invalid key is the one reported. A plain
``frozenset`` has no order, so its keys are sorted."""

from __future__ import annotations

import pyfect as fx
from pyfect import config
from pyfect import config_provider as cp
from pyfect import schema as S
from pyfect.config_provider import Keys, Record

_NUMBERS = S.Record(S.String, S.Number)


def _keys(cfg: config.Config[dict[str, float]], provider: cp.ConfigProvider) -> list[str]:
    return list(fx.run_blocking(cfg.parse(provider).or_die()))


def _first_error(cfg: config.Config[object], provider: cp.ConfigProvider) -> str:
    result = fx.run_blocking(cfg.parse(provider).map_error(lambda e: str(e.cause)).result())
    assert isinstance(result, fx.Err)
    return result.error.splitlines()[-1]


def test_schema_records_follow_the_mapping_order_of_from_unknown():
    provider = cp.from_unknown({"c": 2, "a": 1, "b": 3})

    assert _keys(config.schema(_NUMBERS), provider) == ["c", "a", "b"]
    assert _keys(config.dict_of(S.Number), provider) == ["c", "a", "b"]


def test_schema_records_follow_the_variable_order_of_from_env():
    provider = cp.from_env(env={"c": "2", "a": "1", "b": "3"})

    assert _keys(config.schema(_NUMBERS), provider) == ["c", "a", "b"]


def test_the_first_invalid_key_in_source_order_is_reported():
    provider = cp.from_unknown({"c": "y", "a": "x"})

    assert _first_error(config.schema(_NUMBERS), provider) == '  at ["c"]'


def test_a_record_made_from_keys_lists_them_in_their_order():
    record = Record(Keys(["b", "a", "b"]))

    assert list(record.keys) == ["b", "a"]
    assert record == Record(frozenset({"a", "b"}))


def test_a_record_made_from_a_plain_frozenset_lists_its_keys_sorted():
    record = Record(frozenset({"b", "c", "a"}))

    assert list(record.keys) == ["a", "b", "c"]
    assert record == Record(frozenset({"a", "b", "c"}))
