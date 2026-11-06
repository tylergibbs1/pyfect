"""A check inside a filter group counts as the node's own (QA schema-data
F02): Effect's ``hasCheck`` looks inside ``FilterGroup`` s, so a number
checked by ``isInt32`` / ``isUint32`` (groups holding ``isInt``) or by a
group holding ``isFinite`` is finite to the JSON codec and JSON Schema.

Effect, ``node``::

    toJsonSchemaDocument(Number.check(isInt32())).schema
    // {"type":"integer","allOf":[{"minimum":-9007199254740991,"maximum":9007199254740991},
    //                            {"minimum":-2147483648,"maximum":2147483647}]}
    toJsonSchemaDocument(Number.check(makeFilterGroup([isFinite(), isLessThan(5)]))).schema
    // {"type":"number","allOf":[{"exclusiveMaximum":5}]}

pyfect's ``is_int`` takes any Python ``int``, so its JSON Schema has no
safe-integer bounds (its own decision, not this finding's).
"""

from __future__ import annotations

import ast as pyast
from pathlib import Path

from pyfect import schema as S


def _json_schema(schema: S.Top) -> object:
    return S.to_json_schema_document(schema).schema


def test_is_int32_keeps_its_constraints_in_json_schema():
    assert _json_schema(S.Number.check(S.is_int32())) == {
        "type": "integer",
        "allOf": [{"minimum": -2147483648, "maximum": 2147483647}],
    }


def test_is_uint32_keeps_its_constraints_in_json_schema():
    assert _json_schema(S.Number.check(S.is_uint32())) == {
        "type": "integer",
        "allOf": [{"minimum": 0, "maximum": 4294967295}],
    }


def test_a_group_holding_is_finite_keeps_its_constraints_in_json_schema():
    group = S.make_filter_group(S.is_finite(), S.is_less_than(5))
    assert _json_schema(S.Number.check(group)) == {
        "type": "number",
        "allOf": [{"exclusiveMaximum": 5}],
    }


def test_a_record_keyed_by_an_int32_reads_its_json_keys_as_integers():
    record = S.to_codec_json(S.Record(S.Number.check(S.is_int32()), S.String))
    decoded = S.decode_unknown_sync(record)({"1": "a"})
    assert decoded == {1: "a"}
    assert all(type(key) is int for key in decoded)


SRC = Path(__file__).resolve().parents[2] / "src" / "pyfect"


def _iterates_checks(target: pyast.expr) -> bool:
    if isinstance(target, pyast.BoolOp):  # ``checks or ()``
        target = target.values[0]
    if isinstance(target, pyast.Call) and target.args:  # ``reversed(node.checks or ())``
        return _iterates_checks(target.args[0])
    return (isinstance(target, pyast.Attribute) and target.attr == "checks") or (
        isinstance(target, pyast.Name) and target.id == "checks"
    )


# Loops over checks that compare identities, where a group is one check.
_BY_IDENTITY = frozenset({"schema/_assignable.py", "brand.py"})
# Each hands every check to a function that recurses into groups
# (``_check``; the representation modules' ``check`` / ``_encode_check``;
# the structured-output ``_compiler_check`` / ``_record_check`` /
# ``_append_check_descriptions``; the importer's ``_satisfies_check`` /
# ``_check_has_choices`` / ``_check``).
_DELEGATING = frozenset(
    {
        "ai/_structured_output_checks.py compiler_checks",
        "ai/_structured_output_checks.py record_checks",
        "ai/_structured_output_checks.py structural_annotations",
        "schema/_jsonschema/_compile.py compile",
        "schema/_jsonschema/_compile.py _check",
        "schema/representation/_code_document.py recur",
        "schema/representation/_from.py append_checks",
        "schema/representation/_import/_finalize.py finalize",
        "schema/representation/_import/_intersect.py _satisfies_literal",
        "schema/representation/_import/_intersect.py has_choices",
        "schema/representation/_json.py _encode_checks",
        "schema/representation/_to.py on",
    }
)


def test_every_walk_over_checks_looks_inside_filter_groups():
    """The guard: a loop over a node's checks either handles ``FilterGroup``
    in the same function or goes through ``ast.has_check``."""
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        relative = str(path.relative_to(SRC))
        if relative in _BY_IDENTITY:
            continue
        tree = pyast.parse(path.read_text(), relative)
        for function in pyast.walk(tree):
            if not isinstance(function, pyast.FunctionDef):
                continue
            source = pyast.unparse(function)
            loops = [
                n.iter
                for n in pyast.walk(function)
                if isinstance(n, pyast.For | pyast.comprehension)
            ]
            if f"{relative} {function.name}" in _DELEGATING:
                continue
            if any(map(_iterates_checks, loops)) and "FilterGroup" not in source:
                offenders.append(f"{relative}:{function.lineno} {function.name}")
    assert offenders == [], "handle FilterGroup or use ast.has_check"
