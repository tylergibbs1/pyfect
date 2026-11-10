"""The Python source of pyfect's built-in checks and declarations, by the
``representation`` id ``from_representation`` revives them from (where Effect's
built-ins each carry a ``toCode`` annotation)."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from typing import Any, cast

from pyfect import _json_text
from pyfect.schema.representation._code import (
    Code,
    GeneratedCheck,
    GeneratedDeclaration,
)
from pyfect.schema.representation._model import Json

PREFIX = "effect/schema/"
_NO_ARGUMENTS = frozenset(
    {
        "isTrimmed",
        "isStringFinite",
        "isStringBigInt",
        "isGUID",
        "isULID",
        "isAscii",
        "isBase64",
        "isBase64Url",
        "isUppercased",
        "isLowercased",
        "isCapitalized",
        "isUncapitalized",
        "isFinite",
        "isInt",
        "isUnique",
        "isUniqueKey",
    }
)
_PAIRS = frozenset(
    {"isBetweenLength", "isBetweenCodePoints", "isBetweenSize", "isBetweenProperties"}
)
_BETWEEN = frozenset({"isBetween", "isBetweenDate", "isBetweenBigInt"})
_DATE_FROM_JSON = "S.decode_unknown_sync(S.to_codec_json(S.DateTimeUtc))({value})"


_WORD_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def snake(name: str) -> str:
    """``isBetweenBigInt`` as ``is_between_big_int``; ``isUUID`` as ``is_uuid``."""
    return _WORD_BOUNDARY.sub("_", name).lower()


def string_literal(value: str) -> str:
    """``value`` as a double-quoted Python string."""
    return _json_text.quote(value)


def value_literal(value: object) -> str | None:  # noqa: PLR0911
    """``value`` as a Python expression; ``None`` for what has none."""
    match value:
        case None | bool():
            return repr(value)
        case str():
            return string_literal(value)
        case int():
            return repr(value)
        case float():
            return repr(value) if math.isfinite(value) else f'float("{value}")'
        case list() | tuple():
            return _sequence(cast("list[object]", value))
        case Mapping():
            return _mapping(cast("Mapping[object, object]", value))
        case _:
            return None


def _sequence(values: list[object]) -> str | None:
    items = [value_literal(v) for v in values]
    if any(item is None for item in items):
        return None
    return f"[{', '.join(cast('list[str]', items))}]"


def _mapping(values: Mapping[object, object]) -> str | None:
    entries: list[str] = []
    for key, value in values.items():
        rendered = value_literal(value)
        if not isinstance(key, str) or rendered is None:
            return None
        entries.append(f"{string_literal(key)}: {rendered}")
    return f"{{{', '.join(entries)}}}"


def _bound_value(name: str, value: object) -> str:
    """A bound as a Python expression: a date or a big integer is in its JSON
    form in the payload."""
    if isinstance(value, str) and name.endswith("BigInt"):
        return value
    rendered = cast("str", value_literal(value))
    if isinstance(value, str) and name.endswith("Date"):
        return _DATE_FROM_JSON.format(value=rendered)
    return rendered


def _pattern(payload: Mapping[str, Any]) -> GeneratedCheck:
    source, flags = payload["source"], payload["flags"]
    if flags == "u":
        return GeneratedCheck(f"S.is_ecma_pattern({string_literal(source)})")
    if isinstance(flags, str):
        return GeneratedCheck(
            f"S.is_ecma_pattern({string_literal(source)}, {string_literal(flags)})"
        )
    return GeneratedCheck(
        f"S.is_pattern(re.compile({string_literal(source)}, {flags}))", ("import re",)
    )


def _between(name: str, payload: Mapping[str, Any]) -> str:
    arguments = [
        f"minimum={_bound_value(name, payload['minimum'])}",
        f"maximum={_bound_value(name, payload['maximum'])}",
    ]
    if payload.get("exclusiveMinimum"):
        arguments.append("exclusive_minimum=True")
    if payload.get("exclusiveMaximum"):
        arguments.append("exclusive_maximum=True")
    return ", ".join(arguments)


def check_code(  # noqa: PLR0911
    id: str, payload: Json, schemas: tuple[Code, ...]
) -> GeneratedCheck | None:
    """The source of the built-in check ``id``; ``None`` for any other."""
    if not id.startswith(PREFIX):
        return None
    name = id.removeprefix(PREFIX)
    call = f"S.{snake(name)}"
    fields = cast("Mapping[str, Any]", payload if isinstance(payload, dict) else {})
    if name in _NO_ARGUMENTS:
        return GeneratedCheck(f"{call}()")
    if name == "isPattern":
        return _pattern(fields)
    if name == "isPropertyNames":
        return GeneratedCheck(f"{call}({schemas[0].runtime})")
    if name == "isUUID":
        version = fields.get("version")
        return GeneratedCheck(f"{call}()" if version is None else f"{call}({version})")
    if name in _PAIRS:
        return GeneratedCheck(f"{call}({fields['minimum']}, {fields['maximum']})")
    if name in _BETWEEN:
        return GeneratedCheck(f"{call}({_between(name, fields)})")
    if len(fields) == 1:
        value = next(iter(fields.values()))
        return GeneratedCheck(f"{call}({_bound_value(name, value)})")
    return None


_DATETIME = ("import datetime",)
_FX = "import pyfect as fx"
_CAUSE = "from pyfect import cause"
_FIXED: Mapping[str, tuple[str, str, tuple[str, ...]]] = {
    "Json": ("S.Json", "S.JsonValue", ()),
    "MutableJson": ("S.Json", "S.JsonValue", ()),
    "RegExp": ("S.RegExp", "re.Pattern[str]", ("import re",)),
    "URL": ("S.URL", "url.Url", ("from pyfect.http import url",)),
    "Duration": ("S.Duration", "duration.Duration", ("from pyfect import duration",)),
    "ByteSize": ("S.ByteSize", "byte_size.ByteSize", ("from pyfect import byte_size",)),
    "BigDecimal": ("S.BigDecimal", "big_decimal.BigDecimal", ("from pyfect import big_decimal",)),
    "SemVer": ("S.SemVer", "semver.SemVer", ("from pyfect import semver",)),
    "SemVerRange": (
        "S.SemVerRange",
        "semver_range.SemVerRange",
        ("from pyfect import semver_range",),
    ),
    "Uint8Array": ("S.Bytes", "bytes", ()),
    "DateTimeUtc": ("S.DateTimeUtc", "datetime.datetime", _DATETIME),
    "TimeZoneOffset": ("S.TimeZoneOffset", "datetime.timezone", _DATETIME),
    "TimeZoneNamed": ("S.TimeZoneNamed", "zoneinfo.ZoneInfo", ("import zoneinfo",)),
    "TimeZone": ("S.TimeZone", "datetime.tzinfo", _DATETIME),
    "DateTimeZoned": ("S.DateTimeZoned", "datetime.datetime", _DATETIME),
}
IMPORTED_MODULES = frozenset(
    {
        "byte_size",
        "big_decimal",
        "cause",
        "datetime",
        "fx",
        "graph",
        "semver",
        "semver_range",
        "url",
        "zoneinfo",
    }
)
"""The names the imports above bind, which nothing generated may reuse."""


def _defect(code: Code) -> str:
    """A document holds a defect's JSON side, which pyright does not take for a
    ``BaseException`` schema."""
    return f'cast("Any", {code.runtime})'


_CAST = ("from typing import Any", "from typing import cast")
_PARAMETRIC: Mapping[str, Callable[[tuple[Code, ...]], tuple[str, str, tuple[str, ...]]]] = {
    "Option": lambda p: (f"S.Option({p[0].runtime})", f"fx.Option[{p[0].type}]", (_FX,)),
    "Result": lambda p: (
        f"S.Result({p[0].runtime}, {p[1].runtime})",
        f"fx.Result[{p[0].type}, {p[1].type}]",
        (_FX,),
    ),
    "CauseReason": lambda p: (
        f"S.CauseReason({p[0].runtime}, {_defect(p[1])})",
        f"cause.Reason[{p[0].type}]",
        (_CAUSE, *_CAST),
    ),
    "Cause": lambda p: (
        f"S.Cause({p[0].runtime}, {_defect(p[1])})",
        f"cause.Cause[{p[0].type}]",
        (_CAUSE, *_CAST),
    ),
    "Exit": lambda p: (
        f"S.Exit({p[0].runtime}, {p[1].runtime}, {_defect(p[2])})",
        f"fx.Exit[{p[0].type}, {p[1].type}]",
        (_FX, *_CAST),
    ),
    "ReadonlyMap": lambda p: (
        f"S.Map({p[0].runtime}, {p[1].runtime})",
        f"dict[{p[0].type}, {p[1].type}]",
        (),
    ),
    "ReadonlySet": lambda p: (f"S.FrozenSet({p[0].runtime})", f"frozenset[{p[0].type}]", ()),
}


def _redacted(payload: Json, parameters: tuple[Code, ...]) -> str:
    fields = cast("Mapping[str, Any]", payload if isinstance(payload, dict) else {})
    arguments = [parameters[0].runtime]
    if "label" in fields:
        arguments.append(f"label={string_literal(fields['label'])}")
    if fields.get("disallowJsonEncode"):
        arguments.append("disallow_json_encode=True")
    return f"S.Redacted({', '.join(arguments)})"


def _error(payload: Json) -> str:
    fields = cast("Mapping[str, Any]", payload if isinstance(payload, dict) else {})
    arguments = [
        f"{argument}=True"
        for key, argument in (("includeStack", "include_stack"), ("excludeCause", "exclude_cause"))
        if fields.get(key)
    ]
    return f"S.ErrorInstance.schema({', '.join(arguments)})"


def declaration_code(  # noqa: PLR0911
    id: str, payload: Json, parameters: tuple[Code, ...]
) -> GeneratedDeclaration | None:
    """The source of the built-in declaration ``id``; ``None`` for any other."""
    if not id.startswith(PREFIX):
        return None
    name = id.removeprefix(PREFIX)
    if name in _FIXED:
        runtime, type, imports = _FIXED[name]
        return GeneratedDeclaration(runtime, type, imports)
    if name in _PARAMETRIC:
        return GeneratedDeclaration(*_PARAMETRIC[name](parameters))
    if name == "Redacted":
        return GeneratedDeclaration(
            _redacted(payload, parameters), f"fx.Redacted[{parameters[0].type}]", (_FX,)
        )
    if name == "Error":
        return GeneratedDeclaration(_error(payload), "S.ErrorInstance")
    if name == "Graph":
        node, edge = parameters
        kind = string_literal(cast("str", payload))
        return GeneratedDeclaration(
            f"S.Graph({kind}, {node.runtime}, {edge.runtime})",
            f"graph.Graph[{node.type}, {edge.type}, Literal[{kind}]]",
            ("from pyfect import graph", "from typing import Literal"),
        )
    return None
