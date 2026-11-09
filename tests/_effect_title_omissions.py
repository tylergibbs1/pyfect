"""Effect test titles pyfect does not port, each with its reason.

``tests/test_effect_titles.py`` fails on any Effect title that is neither ported nor matched
here, and on an entry that matches nothing, so this list can only say what is still true.
``path`` is a glob over paths under Effect's ``packages``; ``titles`` is a regular expression
searched in the title, and without one the reason holds for the whole file.

``NOT_PORTED`` is the honest bucket: Python could do it, and pyfect doesn't yet. Its entries
name a section 4 row of ``docs/PARITY.md`` or say why it was not reached.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fnmatch import fnmatch

from _effect_titles_m17 import M17_REASON, TITLES


@dataclass(frozen=True)
class Omission:
    path: str
    reason: str
    titles: re.Pattern[str] | None = None


def _whole(reason: str, *paths: str) -> list[Omission]:
    return [Omission(path, reason) for path in paths]


def _some(path: str, reason: str, pattern: str) -> Omission:
    return Omission(path, reason, re.compile(pattern))


_TS_TOOLING = "the TypeScript monorepo's own tooling, which works on TypeScript sources"
_JS_RUNTIME = "binds a JavaScript runtime or browser API Python doesn't run on"
_UI_BINDING = "binds atoms to a JavaScript UI framework"
_STDLIB = (
    "section 4: the module is Python's own type or standard library, so the title tests Python"
)
_HYPOTHESIS = "section 4: Hypothesis is the property-test runner, shrinker and generator"
_PG_DRIVER = (
    "Effect wrote a PostgreSQL wire driver; pyfect's `sql.pg` runs on psycopg, which has its own"
)
_SYMBOLS = (
    "JavaScript symbols, prototypes, property descriptors, `undefined` or `Date`: no Python value"
)
_NODE_STREAMS = "Node's streams and `EventTarget`: `process`, `socket` and `http` read Python's own"

NOT_PORTED_HTTP2 = "NOT_PORTED HTTP/2 on Node's server: `http.hypercorn_server` differs below ASGI"

OMISSIONS: tuple[Omission, ...] = (
    *(
        Omission(path, M17_REASON, re.compile("|".join(f"^{re.escape(t)}$" for t in titles)))
        for path, titles in TITLES.items()
        if titles
    ),
    *_whole(
        _TS_TOOLING,
        "tools/*/test/**",
    ),
    *_whole(_UI_BINDING, "atom/react/**", "atom/solid/**", "atom/vue/**"),
    *_whole(
        _JS_RUNTIME,
        "platform/browser/**",
        "platform/bun/**",
        "platform/deno/**",
        "sql/sqlite-do/**",
        "sql/sqlite-wasm/**",
        "sql/sqlite-react-native/**",
        "effect/test/EffectKeepAlive.test.ts",
        "effect/test/eventlog/EventJournalIndexedDb.test.ts",
        "effect/test/ai/McpServer/Workerd.test.ts",
    ),
    *_whole(
        "vitest's `it.effect` family; pytest's plugin `pyfect.testing` has its own tests",
        "vitest/test/**",
    ),
    *_whole(
        _STDLIB,
        "effect/test/Array.test.ts",
        "effect/test/ArrayNaNIndex.test.ts",
        "effect/test/BigInt.test.ts",
        "effect/test/Boolean.test.ts",
        "effect/test/Bytes.test.ts",
        "effect/test/Chunk.test.ts",
        "effect/test/Combiner.test.ts",
        "effect/test/Equivalence.test.ts",
        "effect/test/Function.test.ts",
        "effect/test/Iterable.test.ts",
        "effect/test/MutableList.test.ts",
        "effect/test/Newtype.test.ts",
        "effect/test/Number.test.ts",
        "effect/test/Order.test.ts",
        "effect/test/Ordering.test.ts",
        "effect/test/Predicate.test.ts",
        "effect/test/Record.test.ts",
        "effect/test/Reducer.test.ts",
        "effect/test/String.test.ts",
        "effect/test/Struct.test.ts",
        "effect/test/Symbol.test.ts",
        "effect/test/TextDiff.test.ts",
        "effect/test/Tuple.test.ts",
        "effect/test/UndefinedOr.test.ts",
    ),
    *_whole(
        "JavaScript's `Error.stackTraceLimit`; Python's tracebacks have no such limit to restore",
        "effect/test/StackCapture.test.ts",
        "effect/test/StackTraceLimit.test.ts",
    ),
    *_whole(_HYPOTHESIS, "effect/test/arbitrary/**"),
    *_whole(
        "JavaScript's hot module reloading",
        "effect/test/schema/HMR.test.ts",
    ),
    *_whole(
        "the v3 to v4 migration of the TypeScript API; pyfect had no v3",
        "effect/test/schema/v3-v4.test.ts",
    ),
    *_whole(
        _PG_DRIVER,
        "sql/pg/test/ContainerTeardown.test.ts",
        "sql/pg/test/PgAuth.test.ts",
        "sql/pg/test/PgConnection*.test.ts",
        "sql/pg/test/PgProtocol.test.ts",
        "sql/pglite/**",
    ),
    *_whole(
        _NODE_STREAMS,
        "platform/node-shared/test/NodeSink.test.ts",
        "platform/node-shared/test/NodeStream.test.ts",
    ),
    *_whole(
        "sql/pg's own OIDs and text/binary codecs: psycopg's adapters read those types",
        "sql/pg/test/PgTypes.test.ts",
    ),
    *_whole(
        _JS_RUNTIME,
        "effect/test/encoding/Base64.test.ts",
        "effect/test/internal/Uuid.test.ts",
        "effect/test/rpc/RpcSerialization.test.ts",
    ),
    *_whole(
        "section 4: `__eq__` and `hash` are the equality; proxies and symbols are JavaScript's",
        "effect/test/Equal.test.ts",
        "effect/test/Hash.test.ts",
    ),
    *_whole(
        "section 4 `Formatter.format`: `format_unknown` covers Python values; these are JS objects",
        "effect/test/Formatter.test.ts",
    ),
    *_whole(
        "section 4: Python's `match` statement is the pattern matcher",
        "effect/test/Match.test.ts",
    ),
    *_whole(
        "a module-level version constant; `importlib.metadata` is Python's way",
        "effect/test/Version.test.ts",
    ),
    *_whole(
        "section 4: a DateTime is an aware `datetime` and this is the standard library",
        "effect/test/DateTime.test.ts",
    ),
    _some(
        "effect/test/Duration.test.ts",
        "section 4: a Duration is `duration.Seconds` or `timedelta`; `to_*` are arithmetic there, "
        "and `Hash` / `Combiner` are Python's (input forms: tests/oracle/test_duration.py)",
        r"^(?!fromInput|converts large finite|toMillis$|toSeconds$)",
    ),
    *_whole(
        "`is*` guards are `isinstance`, `_tag` strings are classes (section 4), and the rest is "
        "Node inspection and `Error.stackTraceLimit`",
        "effect/test/Cause.test.ts",
    ),
    *_whole(
        _NODE_STREAMS,
        "effect/test/Channel.test.ts",
        "effect/test/Sink.test.ts",
    ),
    _some("effect/test/Stream.test.ts", _NODE_STREAMS, r"event|ReadableStream"),
    *_whole(
        "the suite needs a BIND container and `node:dns`; `tests/oracle/test_dns.py` ports `Dns`",
        "platform/node-shared/test/Dns.test-utils.ts",
    ),
    *_whole(NOT_PORTED_HTTP2, "platform/node-shared/test/HttpServerHttp2.test-utils.ts"),
    _some(
        "platform/node/test/NodeHttpClient.test.ts",
        "NOT_PORTED client-side `Connection: Upgrade`, reached only by Node's agent",
        r"upgraded connection|101 response",
    ),
    _some(
        "platform/node/test/NodeSocket.test.ts",
        _NODE_STREAMS,
        r"writable stream rejection|^works$",
    ),
    _some(
        "effect/test/Result.test.ts",
        "section 4 `Do / bind` row: generator locals, as pyright can't type a growing record",
        r"^(Do|bindTo|bind|let)$",
    ),
    *_whole(
        "NOT_PORTED a TCP chaos proxy against PostgreSQL and MySQL; "
        "`test_sql_runner_storage.py` covers the reserved connection without one",
        "platform/node/test/cluster/SqlRunnerStorage.integration.test.ts",
    ),
    _some(
        "effect/test/ai/McpServer/McpConformance/LoggingTest.ts",
        "a TypeScript `SCHEMA` constant template, rendered per protocol in `test_mcp_*`",
        r"SCHEMA",
    ),
    _some(
        "effect/test/httpapi/HttpApiBuilder.test.ts",
        "NOT_PORTED `handlers.handleAll`: one handler per endpoint is the only form here",
        r"handleAll",
    ),
    _some(
        "effect/test/httpapi/HttpApiBuilder.test.ts",
        "a memo of a transformation by source AST, an identity not observable in Python",
        r"reuses response schema",
    ),
    # --- Schema: the module docstrings of tests/oracle/test_schema*.py give these groups.
    *_whole(
        _SYMBOLS,
        "effect/test/schema/representation/fromJson.test.ts",
        "effect/test/schema/toFormatter.test.ts",
        "effect/test/schema/toEquivalence.test.ts",
        "effect/test/schema/SchemaParser.test.ts",
    ),
    _some("effect/test/schema/SchemaAST.test.ts", _SYMBOLS, r"unique symbol sentinels|^Symbol$"),
    *_whole(
        "section 4 `Schema.File` row: form-data getters are not ported with their schemas",
        "effect/test/schema/SchemaGetter.test.ts",
    ),
    _some(
        "effect/test/schema/toCodec.test.ts",
        _SYMBOLS,
        r"Any should be|Date|Cause\(Option|top-level AST|named reference|branded members",
    ),
    _some(
        "effect/test/schema/representation/stringTreeRoundtrip.test.ts",
        "`to_code_document` writes the types into Python source, covered by its own suite",
        r"value types|property name",
    ),
    _some(
        "effect/test/schema/Schema.test.ts",
        _SYMBOLS,
        r"FormData|fromURLSearchParams|immerable|^Equality$|__proto__|name and length"
        r"|symbol|Symbol",
    ),
    _some(
        "effect/test/schema/Schema.test.ts",
        "section 4 `Schema.mutable` / `mutableKey` / `readonlyKey` row: Python types have no "
        "`readonly`, so a key has no mutability to set or clear",
        r"^readonlyKey$|mutableKey\(",
    ),
    _some(
        "effect/test/schema/Schema.test.ts",
        "section 4 `Schema.UndefinedOr` row: Python has one `None`, so `UndefinedOr` / "
        "`NullishOr` are `S.NullOr` and `optional` / `requiredKey` / `required` are "
        "`S.optional_key` and a required TypedDict key",
        r"^UndefinedOr\(String\)$|^NullishOr\(String\)$|^Schema\.optional:"
        r"|optional\(Number\)\) should|keys required$",
    ),
    _some(
        "effect/test/schema/Schema.test.ts",
        "section 4 row of this title: a class constructor is its fields' Python signature, and "
        "taking unknown keys needs `**kwargs`, which loses pyright's field-name checks",
        r"strips excess properties with explicit ignore",
    ),
    _some(
        "effect/test/schema/Schema.test.ts",
        "section 4 `Schema.UndefinedOr` row: Python has one `None`, so `OptionFromOptional` is "
        "`S.OptionFromOptionalNullOr` or `S.OptionFromOptionalKey`",
        r"^OptionFromOptional$",
    ),
    _some(
        "effect/test/schema/Schema.test.ts",
        "`class A extends Schema.String`: a Python schema is a value, and pyright rejects a value "
        "as a base class (`__mro_entries__` runs, but: Argument to class must be a base class)",
        r"^subclassing$|^wrapping a|^inherits the schema protocol$|^extending a rebuilt schema$"
        r"|^static (getter|property)|^does not create class instances$",
    ),
    _some(
        "effect/test/schema/Schema.test.ts",
        "section 4: `Struct` keys are mapped with Python comprehensions, not `mapFields` helpers",
        r"evolveEntries|evolveKeys|mapOmit|mapPick|renameKeys|^should work with flow$",
    ),
)


def reason_for(path: str, title: str) -> str | None:
    """The reason ``title`` of Effect's file ``path`` is omitted, if it is."""
    for omission in OMISSIONS:
        if fnmatch(path, omission.path) and (
            omission.titles is None or omission.titles.search(title) is not None
        ):
            return omission.reason
    return None
