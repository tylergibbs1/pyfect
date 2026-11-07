"""``Schema.Defect`` writing a value JSON has no form for: Effect's ``encodeUnknownAsJson``
is what ``Formatter.formatJson`` reads, so ``JSON.stringify``'s rules hold. Each expected value
is from ``Schema.encodeUnknownSync(Schema.Defect())`` under Node."""

from datetime import UTC, datetime

import pytest

from pyfect import schema as S


def _function() -> None: ...


class _Fields:
    def __init__(self) -> None:
        self.a = 1


_CIRCULAR: dict[str, object] = {"x": 1}
_CIRCULAR["self"] = _CIRCULAR


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (_function, None),
        ({"a": _function}, {}),
        ([_function], [None]),
        (_Fields, None),
        (_Fields(), {"a": 1}),
        ({1}, {}),
        (float("nan"), None),
        (float("inf"), None),
        (datetime(1970, 1, 1, tzinfo=UTC), "1970-01-01T00:00:00.000Z"),
        (_CIRCULAR, {"x": 1}),
        ({"e": ValueError("x")}, {"e": {"name": "ValueError", "message": "x"}}),
        (b"\x01\x02", {"0": 1, "1": 2}),
    ],
    ids=[
        "function",
        "object_function",
        "list_function",
        "class",
        "instance",
        "set",
        "nan",
        "inf",
        "date",
        "circular",
        "nested_error",
        "bytes",
    ],
)
def test_a_defect_without_json_is_written_as_format_json_reads_it(
    value: object, expected: object
) -> None:
    assert S.encode_unknown_sync(S.Defect())(value) == expected
