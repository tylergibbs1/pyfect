"""Effect 4.1.5 test titles not ported yet (milestone M19, the move from Effect 4.1.4).

Each M19 area ports the titles of its files and deletes them here; an empty ``TITLES`` closes
the milestone. ``tests/_effect_title_omissions.py`` lists every title here as NOT_PORTED.
"""

from __future__ import annotations

M19_REASON = "NOT_PORTED new in Effect 4.1.5 (milestone M19), not ported yet"

TITLES: dict[str, tuple[str, ...]] = {
    "ai/openai/test/OpenAiClient.test.ts": ("preserves WebSocket error details with $name",),
    "chat/discord/test/interactions.test.ts": (
        "followUp sends one HTTP request through dfx's layers on a 429 just before 15 minutes, and fails RateLimited",
    ),
    "chat/slack/test/live.test.ts": (
        "a post or edit stores no token unless allowed, and an allowed user as a token and element",
        "a stream split inside an allowed token stores it whole, suppresses the rest and leaves no U+200B",
    ),
    "chat/telegram/test/TelegramChat.test.ts": (
        "answers 413 for a body that middleware read first, past the limit",
        "commandRequests refuses ids Telegram can't register",
        "dispatches only data from Telegram's copy of the keyboard, and answers every click",
        "gives an anonymous admin's command the group as its user",
        "keeps the secret out of server spans that capture every header, set up as the README says",
    ),
    "effect/test/Cache.test.ts": (
        "%s expires from lookup completion after the first caller is interrupted",
    ),
    "effect/test/Codegen.test.ts": (
        "can keep accumulating after finalization without changing previous output",
        "emits only used imports, groups named imports, and promotes type imports",
        "formats literals, keys, documentation, and indented fragments",
        "keeps exact names and prevents shadowing along nested scopes",
        "keeps independently created modules isolated",
        "preserves recursive schemas and initializes their eager consumers",
        "rejects eager cycles and distinguishes imports requesting the same name",
        "renders shared fragments once per finalization",
        "resolves bindings and dependency order without changing literal text",
        "shares import symbols across modules and prints without mutating names",
        "shares names, imports and symbol identities with the rest of the module",
    ),
    "effect/test/Effect.test.ts": (
        "\x00 defers startup by default and starts synchronously when requested",
        "\x00 waits for asynchronous finalizers",
        "an explicitly interruptible region overrides the uninterruptible fork option",
        "raceAll interrupts losers under an uninterruptible parent",
        "raceFirst interrupts the loser under an uninterruptible parent",
        "recovers from Effect.interrupt with the current fiber as interruptor",
        "registers a fiber even when it interrupts its forker during startup",
        "suspend treats a thrown value as a defect",
        "timeout waits for an uninterruptible source but discards its success",
        "uninterruptible: \x00 when forked from an \x00 region",
    ),
    "effect/test/Fiber.test.ts": (
        "\x00 cancellation does not interrupt an independently owned fiber",
    ),
    "effect/test/FiberHandle.test.ts": (
        "join ignores managed replacement interruptions and reports child errors without closing the handle",
        "run registers a fiber even when it interrupts its forker during startup",
    ),
    "effect/test/FiberMap.test.ts": (
        "join reports the first failure without interrupting siblings or closing the map",
        "run registers a fiber even when it interrupts its forker during startup",
    ),
    "effect/test/FiberSet.test.ts": (
        "join reports the first failure without interrupting siblings or closing the set",
        "run registers a fiber even when it interrupts its forker during startup",
    ),
    "effect/test/HashMap.test.ts": ("handles custom hashes that are not 32-bit integers",),
    "effect/test/Queue.test.ts": (
        "the final take delivers before a closing queue notifies its awaiters",
    ),
    "effect/test/Scope.test.ts": (
        "runs finalizers one at a time in reverse registration order by default",
    ),
    "effect/test/ScopedCache.test.ts": (
        "expires from lookup completion after the first caller is interrupted",
    ),
    "effect/test/Stream.test.ts": (
        "does not open the next iterator until requested",
        "emits ordered chunks before propagating an upstream failure",
        "filterEffect - passes stream indices across chunks on each execution",
        "stops pulling an infinite iterable early",
    ),
    "effect/test/Trie.test.ts": (
        "toEntriesWithPrefix preserves prefix boundaries and UTF-16 order",
    ),
    "effect/test/ai/McpServer/LayerHttpRequestScoped.test.ts": (
        "answers an asynchronous tools/call before a scheduler round runs",
    ),
    "effect/test/ai/McpServer/McpServer.test.ts": (
        "downgrades unsupported toModelOutput blocks to text on 2024-11-05",
        "uses toModelOutput parts as tool result content while preserving structuredContent",
    ),
    "effect/test/chat/ChatTest.test.ts": (
        "ChatHandler.layer drops the bot's own messages unless deliverSelf",
        "conformance \x00 without \x00",
    ),
    "effect/test/cli/Help.test.ts": (
        "constructs the segmenter only on the first width calculation",
    ),
    "effect/test/cluster/Sharding.test.ts": (
        "unregisters during persistent lock failures despite successful empty probes",
    ),
    "effect/test/internal/Utf8.test.ts": ("decodes a %i-byte slice like TextDecoder",),
    "effect/test/reactivity/Atom.test.ts": (
        "searchParam cancels stale writes but preserves observer writes (%s)",
    ),
    "effect/test/schema/representation/codeExpression.test.ts": (
        "inserts supplied fragments without parsing or renaming their contents",
        "preserves escaped strings, numeric literals and comments when renaming references",
        "rejects unsupported syntax instead of guessing about local bindings",
        "rewrites namespace references inside arguments without rewriting members, keys or text",
        "supports nested calls, literal arguments and the generated type forms",
    ),
    "effect/test/schema/representation/codeImports.test.ts": (
        "preserves evaluation order, attributes and runtime imports when deduplicating",
        "reads local bindings from import syntax",
        "rejects malformed imports",
    ),
    "effect/test/schema/representation/codegen.annotations.test.ts": (
        "compiles the isPattern and Option vertical slice",
        "emits references that are not reachable from a root",
        "emits supported annotation trees atomically",
        "emits tuple element and property annotations",
        "generates a StructWithRest without fixed properties",
        "generates content media types, optional pre-rest elements and numeric properties",
        "makes colliding sanitized reference identifiers unique",
        "omits unsupported object annotations atomically",
        "orders a shared dependency referenced from multiple representation positions once",
        "orders definitions after dependencies found in every representation position",
        "passes compiled dependencies to checks and deduplicates imports",
        "passes type parameters to declaration callbacks",
        "preserves a lowercase identifier annotation",
        "preserves explicit options on a single-literal Union",
        "preserves explicit options on an empty union",
        "preserves fallback identifiers",
        "preserves optional Union option properties",
        "preserves top-level and nested __proto__ annotations in generated code",
        "rejects imports that reuse a callback argument without retrying",
        "reports a missing reference from a definition",
        "reports missing references with their document path",
        "reports missing toCode callbacks and preserves callback exceptions",
        "reports unsupported callback syntax with its document path",
        "sanitizes reference identifiers",
        "uses group overrides without visiting children and preserves abort",
    ),
    "effect/test/schema/representation/codegen.test.ts": (
        "allows an import named Array",
        "avoids collisions between reference names and declaration imports",
        "avoids collisions between references and symbol or enum artifacts",
        "deduplicates imports across definitions and roots",
        "emits every member of a productive mutual cycle",
        "emits unreachable definitions",
        "initializes mixed dependencies and disconnected recursive components in either record order",
        "keeps colliding sanitized identifiers distinct",
        "keeps distinct symbols with identical descriptions distinct",
        "keeps generated names from shadowing emitted globals",
        "keeps union combinations compact",
        "orders a diamond dependency once regardless of input order",
        "orders an eager reference in a \x00",
        "orders dependencies passed to a \x00",
        "orders numeric identifiers regardless of reference enumeration",
        "preserves \x00",
        "preserves Void's discarded input behavior",
        "preserves node, check and key annotations at their original locations",
        "propagates renamed imports through nested declaration callbacks",
        "reports missing callback for \x00",
        "resolves callback-local imports while preserving declaration names and literal text",
        "resolves imports colliding with symbol and enum artifacts",
        "resolves imports returned by check callbacks",
        "resolves named and type-only imports without repeating callbacks",
        "reuses the Schema import without rerunning callbacks",
        "self recursion with \x00",
    ),
    "effect/test/testing/TestSchema.test.ts": (
        "round trips accept a negative zero that decodes back to positive zero",
    ),
    "platform/node/test/NodeHttpPlatform.test.ts": ("fileWeb reads the requested byte range",),
    "platform/node/test/NodeHttpServer.test.ts": (
        "a websocket highWaterMark pauses the peer instead of closing it",
        "answers a POST before serving starts",
        "keeps an error listener on the request after a streamed body is aborted",
    ),
    "platform/node/test/cluster-integration/Persistence.test.ts": (
        "\x00: replays a request whose reply was fenced by a slow lock check",
    ),
    "platform/node/test/cluster/SqlMessageStorage.integration.test.ts": (
        "guarded clearReplies preserves a concurrently saved reply in either lock order",
    ),
    "sql/mssql/test/SqlEventLogServerEncrypted.integration.test.ts": (
        "opens a store while another instance is creating an index",
    ),
    "sql/pg/test/Client.integration.test.ts": (
        "reads anonymous records and record arrays",
        "times out a queued stream before the transaction connection is released",
    ),
}
