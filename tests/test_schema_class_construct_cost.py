"""Constructing a schema class with checks on parses each field's value once, as with
``disable_checks``, and does not parse the values again as a struct when they pass: in
Effect, ``new Entry(props)`` costs what ``new Entry(props, { disableChecks: true })`` does.

pyfect parsed the fields, then collected the values into a dict and parsed it through the
constructor's struct (``ast.Objects``) again, twice the cost (3.5 against 1.9 us an
``eventlog.Entry``). That parse now runs only for a construction that fails, to build its
issue."""

from typing import Any

import pytest

from pyfect import schema as S


class _Plain(S.Class):
    id: bytes = S.field(S.Bytes)
    event: str = S.field(S.String)
    sequence: int = S.field(S.Int.check(S.is_greater_than_or_equal_to(0)))


def _struct_parses(monkeypatch: pytest.MonkeyPatch) -> list[S.ast.Objects]:
    parsed: list[S.ast.Objects] = []
    parse = S.ast.Objects.parse

    def counted(self: S.ast.Objects, *args: Any, **kwargs: Any) -> Any:
        parsed.append(self)
        return parse(self, *args, **kwargs)

    monkeypatch.setattr(S.ast.Objects, "parse", counted)
    return parsed


def test_a_passing_construction_with_checks_on_parses_no_struct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _Plain(id=b"", event="e", sequence=0)  # built before counting
    parsed = _struct_parses(monkeypatch)
    _Plain(id=b"", event="e", sequence=1)
    S.new(_Plain, disable_checks=True)(id=b"", event="e", sequence=2)
    assert parsed == []


def test_a_field_check_still_fails_the_construction() -> None:
    with pytest.raises(S.SchemaError, match="greater than or equal to 0"):
        _Plain(id=b"", event="e", sequence=-1)
    assert S.new(_Plain, disable_checks=True)(id=b"", event="e", sequence=-1).sequence == -1
