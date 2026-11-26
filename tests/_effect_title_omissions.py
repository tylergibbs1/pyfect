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

from _effect_titles_m18 import M18_REASON
from _effect_titles_m18 import TITLES as M18_TITLES
from _effect_titles_m19 import M19_REASON
from _effect_titles_m19 import TITLES as M19_TITLES


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
_WORKERD = (
    "binds Cloudflare's workerd: Durable Objects, their storage and alarms exist only inside it, "
    "and pyfect's runtime is CPython with threads, which Python Workers (Pyodide) do not have"
)
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
        Omission(path, reason, re.compile("|".join(f"^{re.escape(t)}$" for t in titles)))
        for reason, listed in ((M18_REASON, M18_TITLES), (M19_REASON, M19_TITLES))
        for path, titles in listed.items()
        if titles
    ),
    *_whole(
        _TS_TOOLING,
        "tools/*/test/**",
    ),
    *_whole(_WORKERD, "platform/cloudflare/**"),
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
        "Node's `inspect` hook; Python's `repr` is pinned in tests/oracle/test_duration.py",
        r"^inspect$",
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
    _some(
        "effect/test/persistence/PersistedQueueTest.ts",
        'the suite runs it only for a store built with `cleanup: "unsupported"`, which only '
        "Cloudflare's Durable Object store is (`platform/cloudflare`, not ported); every pyfect "
        "store supports cleanup and runs the suite's cleanup cases",
        r"^cleanup explicitly fails as unsupported$",
    ),
    _some(
        "effect/test/eventlog/EventJournal.test.ts",
        "an imported id more than a day ahead of the clock is not the floor of local ids, so one "
        "at the UUID v7 ceiling no longer stops every local write (Effect's do fail); "
        "tests/test_eventlog_entry_id_floor.py pins it",
        r"^never commits a local id below an imported id at the maximum timestamp$",
    ),
    _some(
        "platform/node-shared/test/Dns.test-utils.ts",
        "the system resolver queries only PTR records (`resolve` of other types fails with "
        "`Unsupported`); `tests/oracle/test_dns_system.py` ports the PTR and reverse titles",
        r"every record type|TLSA|TXT record|no record can be represented|refused",
    ),
    _some(
        "platform/node/test/cluster-integration/Entity.test.ts",
        "section 4 row of these two titles: out of date at Effect 4.1.2, which ends a frozen "
        "lock session after `shard_lock_expiration` (it times out under Node); "
        "`test_releases_frozen_advisory_locks_after_the_lock_expiration` asserts 4.1.2",
        r"retains frozen advisory locks until the session closes",
    ),
    _some(
        "platform/node/test/cluster-integration/Locks.test.ts",
        "section 4 row of these two titles: out of date at Effect 4.1.2, whose rebuilt lock "
        "session drops the shards it does not hold (it fails under Node on pg); "
        "`test_drops_shards_on_lock_connection_rebuilds_and_converges_after_a_hung_release` "
        "asserts 4.1.2",
        r"converges after repeated lock-connection rebuilds and a hung release",
    ),
    *_whole(NOT_PORTED_HTTP2, "platform/node-shared/test/HttpServerHttp2.test-utils.ts"),
    _some(
        "effect/test/http/FetchHttpClient.test.ts",
        "section 4 `StreamBodyFallback` row: a fetch runtime without streaming request bodies; "
        "httpx streams every stream body",
        r"unsupported streaming",
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
        "a memo of a transformation by source AST, an identity not observable in Python",
        r"reuses response schema",
    ),
    _some(
        "effect/test/httpapi/HttpApiBuilder.test.ts",
        "section 4 `HttpApiBuilder.handleAll` row: `handle_all` takes `builder.entry` values, "
        "not a record, so there are no inherited properties to ignore",
        r"^ignores inherited handleAll properties$",
    ),
    # Effect 4.1.5 (#10704) reads enumerable own symbol keys of a record argument and skips
    # non-enumerable and inherited ones; a Python mapping has neither.
    *(
        _some(path, _SYMBOLS, r"symbol fields|symbol values|symbol entries|non-enumerable")
        for path in (
            "effect/test/cli/Command.test.ts",
            "effect/test/cli/Prompt.test.ts",
            "effect/test/Config.test.ts",
            "effect/test/Effect.test.ts",
            "effect/test/LayerMap.test.ts",
            "effect/test/Option.test.ts",
            "effect/test/reactivity/AsyncResult.test.ts",
            "effect/test/Request.test.ts",
            "effect/test/Result.test.ts",
            "effect/test/schema/VariantSchema.test.ts",
            "effect/test/testing/TestSchema.test.ts",
        )
    ),
    *_whole(
        "Effect's own UTF-8 decoder for short byte slices, checked against `TextDecoder`; "
        "Python decodes with `bytes.decode`",
        "effect/test/internal/Utf8.test.ts",
    ),
    _some(
        "effect/test/cli/Help.test.ts",
        _JS_RUNTIME + ": `Intl.Segmenter`, built on first use; `display_width` reads `unicodedata`",
        r"^constructs the segmenter only on the first width calculation$",
    ),
    _some(
        "platform/node/test/NodeHttpServer.test.ts",
        _NODE_STREAMS + ": the request's `error` listener after an aborted body (Effect #10794)",
        r"^keeps an error listener on the request after a streamed body is aborted$",
    ),
    _some(
        "chat/discord/test/interactions.test.ts",
        "Effect's Discord adapter runs its HTTP calls through dfx, the JavaScript Discord library;"
        " pyfect's port of the behaviour is \"followUp sends one HTTP request on a 429 just before"
        " 15 minutes, and fails RateLimited\" (Effect 4.1.5 added dfx's layers to the title)",
        r"^followUp sends one HTTP request through dfx's layers",
    ),
    _some(
        "chat/slack/test/live.test.ts",
        "runs only against a real Slack workspace, given `SLACK_LIVE_*` tokens CI never sets;"
        " pyfect checks its Slack adapter against the fake of `tests/_slack_fake.py`",
        r"^a post or edit stores no token unless allowed|^a stream split inside an allowed token",
    ),
    _some(
        "effect/test/TestClock.test.ts",
        "section 4: `JSON.stringify` of a context and of a spread copy of the clock, JavaScript's "
        "object model; a Python context is not JSON and a service is not copied by spreading",
        r"^serializes a context containing a TestClock$",
    ),
    _some(
        "platform/node/test/RpcServer.test.ts",
        "pyfect shares the array across processes: a process worker's message carries the "
        "segment's name, so the child maps the caller's memory and writes into it "
        "(`test_workers_shared_memory.py`)",
        r"^a child process rejects a shared array instead of copying it$",
    ),
    # --- Schema: the module docstrings of tests/oracle/test_schema*.py give these groups.
    *_whole(
        _SYMBOLS,
        "effect/test/schema/representation/fromJson.test.ts",
        "effect/test/schema/toFormatter.test.ts",
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


def open_title_count(unported: dict[str, list[str]]) -> int:
    """How many of the unported titles are ``NOT_PORTED``, per occurrence: a file can repeat a
    title under other ``describe`` blocks. docs/PARITY.md states it (``_parity_counts.py``)."""
    return sum(
        (reason_for(path, title) or "").startswith("NOT_PORTED")
        for path, titles in unported.items()
        for title in titles
    )
