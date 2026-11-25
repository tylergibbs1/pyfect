"""``scripts/ai_generated_migration.py``: a name a regeneration drops is listed as renamed
only when one new name matches it, else as removed."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _script() -> Any:
    spec = importlib.util.spec_from_file_location(
        "ai_generated_migration", ROOT / "scripts" / "ai_generated_migration.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up
    spec.loader.exec_module(module)
    return module


migration = _script()

_EVENT = '_b.struct(_T.{name}, {{"n": {n}, "type": _b.literal("done")}})'
_INT = '_b.check(_S.Number, _S.is_int().annotate(expected="an integer"))'


def test_a_struct_with_the_same_fields_is_renamed_whatever_its_annotations():
    old = {"BaseDone": _EVENT.format(name="BaseDone", n=_INT) + '.annotate(identifier="BaseDone")'}
    new = {"Done": _EVENT.format(name="Done", n="_S.Int") + '.annotate(description="d")'}
    changes = migration.match_names(old, new)
    assert changes.renamed == {"BaseDone": "Done"}
    assert changes.removed == ()


def test_a_schema_with_the_same_description_is_renamed():
    old = {"Old": '_S.String.annotate(description="The id")'}
    new = {"New": '_b.check(_S.String, _S.is_min_length(1)).annotate(description="The id")'}
    assert migration.match_names(old, new).renamed == {"Old": "New"}


def test_a_name_kept_in_the_new_package_can_replace_one_that_is_gone():
    old = {
        "CompletedEvent": _EVENT.format(name="CompletedEvent", n="_S.Int"),
        "Completed": _EVENT.format(name="Completed", n="_S.Int"),
    }
    new = {"Completed": _EVENT.format(name="Completed", n="_S.Int")}
    assert migration.match_names(old, new).renamed == {"CompletedEvent": "Completed"}


def test_two_candidates_or_a_common_shape_leave_the_name_removed():
    old = {"Gone": _EVENT.format(name="Gone", n="_S.Int"), "Ids": "_b.array(_S.String)"}
    new = {
        "A": _EVENT.format(name="A", n="_S.Int"),
        "B": _EVENT.format(name="B", n="_S.Int"),
        "Names": "_b.array(_S.String)",
    }
    assert migration.match_names(old, new).removed == ("Gone", "Ids")


def test_numbered_names_are_never_matched():
    old = {"Objects_3": _EVENT.format(name="Objects_3", n="_S.Int")}
    new = {"Done": _EVENT.format(name="Done", n="_S.Int")}
    assert migration.match_names(old, new).removed == ("Objects_3",)


def test_a_nested_type_follows_its_renamed_parent():
    old = {
        "Old": '_t.TypedDict("Old", {"a": "Old__a"})',
        "Old__a": '_t.TypedDict("Old__a", {"x": "str"})',
    }
    new = {
        "New": '_t.TypedDict("New", {"a": "New__a"})',
        "New__a": '_t.TypedDict("New__a", {"x": "str", "y": "int"})',
    }
    assert migration.match_names(old, new).renamed == {"Old": "New", "Old__a": "New__a"}


def test_a_client_method_is_matched_by_its_http_method_and_path():
    changes = migration.match_methods(
        {"get_thing": "GET /things/{}"}, {"read_thing": "GET /things/{}"}
    )
    assert changes.renamed == {"get_thing": "read_thing"}
