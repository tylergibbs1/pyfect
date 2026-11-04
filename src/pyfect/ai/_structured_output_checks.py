"""The checks of a structured output's rewritten nodes (Effect's
``internal/structured-output.ts``): checks without the ``expected`` text a
JSON Schema type already says, no-op copies of the checks the JSON Schema
compiler needs, a record's lower size bounds as bounds of its entries, and
the description of a rewritten shape."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any, cast

from pyfect.schema import ast as A
from pyfect.schema import is_min_length
from pyfect.schema._jsonschema._checks import exporter

_UNDESCRIBED = frozenset({"effect/schema/isFinite", "effect/schema/isInt"})
"""The checks whose ``expected`` text is left out of descriptions: their
JSON Schema type says it."""
_DOCUMENTATION = ("description", "expected", "title")


def _without(annotations: A.Annotations | None, keys: tuple[str, ...]) -> A.Annotations:
    return {k: v for k, v in (annotations or {}).items() if k not in keys}


def prepare_checks(checks: A.Checks | None) -> A.Checks | None:
    """``checks`` without the ``expected`` text of ``is_finite`` / ``is_int``."""
    if checks is None:
        return None
    out = tuple(map(_prepare_check, checks))
    if all(a is b for a, b in zip(out, checks, strict=True)):
        return checks
    return cast("A.Checks", out)


def _prepare_check(check: A.Check[Any]) -> A.Check[Any]:
    if isinstance(check, A.FilterGroup):
        checks = prepare_checks(check.checks)
        return check if checks is check.checks else replace(check, checks=checks)
    id = _representation(check.annotations).get("id")
    if id in _UNDESCRIBED:
        return replace(check, annotations=_without(check.annotations, ("expected",)))
    return check


def _representation(annotations: A.Annotations | None) -> Mapping[str, object]:
    representation = (annotations or {}).get("representation")
    return (
        cast("Mapping[str, object]", representation) if isinstance(representation, Mapping) else {}
    )


def _skip(_: object, __: A.AST, ___: object) -> None:
    return None


def compiler_checks(checks: A.Checks | None) -> A.Checks | None:
    """No-op copies of the checks that have a JSON Schema fragment: a
    rewritten node gives the compiler its own JSON type without running the
    original check on the rewritten shape."""
    if checks is None:
        return None
    out = [c for check in checks for c in _compiler_check(check)]
    return cast("A.Checks", tuple(out)) if out else None


def _compiler_check(check: A.Check[Any]) -> list[A.Check[Any]]:
    annotations = _compiler_annotations(check.annotations)
    if isinstance(check, A.FilterGroup):
        checks = compiler_checks(check.checks)
        if checks is not None:
            return [A.FilterGroup(checks, annotations)]
    return [] if annotations is None else [A.Filter(_skip, annotations)]


def _compiler_annotations(annotations: A.Annotations | None) -> A.Annotations | None:
    if exporter(annotations) is None:
        return None
    kept = ("representation", "to_json_schema")
    return {k: v for k, v in (annotations or {}).items() if k in kept}


def record_checks(checks: A.Checks | None) -> A.Checks | None:
    """The lower size bounds of a record, as bounds of its entries. Upper
    bounds are left out: duplicate keys collapse when decoding, so a
    ``max_items`` could reject entries the codec accepts."""
    if checks is None:
        return None
    out = [c for check in checks for c in _record_check(check)]
    return cast("A.Checks", tuple(out)) if out else None


def _record_check(check: A.Check[Any]) -> list[A.Check[Any]]:
    if isinstance(check, A.FilterGroup):
        return [c for child in check.checks for c in _record_check(child)]
    representation = _representation(check.annotations)
    payload = representation.get("payload")
    if not isinstance(payload, Mapping):
        return []
    payload = cast("Mapping[str, object]", payload)
    match representation.get("id"):
        case "effect/schema/isMinProperties":
            minimum = payload.get("minProperties")
        case "effect/schema/isBetweenProperties":
            minimum = payload.get("minimum")
        case _:
            return []
    if not isinstance(minimum, int | float):
        return []
    filter = is_min_length(minimum)
    return [replace(filter, annotations=_without(filter.annotations, _DOCUMENTATION))]


def structural_annotations(node: A.AST, description: str) -> A.Annotations:
    descriptions: list[str] = []
    _append_description(descriptions, node.annotations)
    for check in node.checks or ():
        _append_check_descriptions(descriptions, check)
    if not descriptions:
        return {"description": description}
    return {"description": f"{description}; {' and '.join(descriptions)}"}


def _append_check_descriptions(descriptions: list[str], check: A.Check[Any]) -> None:
    _append_description(descriptions, check.annotations)
    if isinstance(check, A.FilterGroup):
        for child in check.checks:
            _append_check_descriptions(descriptions, child)


def _append_description(descriptions: list[str], annotations: A.Annotations | None) -> None:
    annotations = annotations or {}
    description = annotations.get("description")
    if description is None:
        description = annotations.get("expected")
    if isinstance(description, str) and description not in descriptions:
        descriptions.append(description)
