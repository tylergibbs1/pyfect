"""Effect 4.1.5 test titles not ported yet (milestone M19, the move from Effect 4.1.4).

Each M19 area ports the titles of its files and deletes them here; an empty ``TITLES`` closes
the milestone. ``tests/_effect_title_omissions.py`` lists every title here as NOT_PORTED.
"""

from __future__ import annotations

M19_REASON = "NOT_PORTED new in Effect 4.1.5 (milestone M19), not ported yet"

TITLES: dict[str, tuple[str, ...]] = {
    "chat/telegram/test/TelegramChat.test.ts": (
        "keeps the secret out of server spans that capture every header, set up as the README says",
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
        "rejects imports that reuse a callback argument without retrying",
        "reports unsupported callback syntax with its document path",
        "sanitizes reference identifiers",
    ),
    "effect/test/schema/representation/codegen.test.ts": (
        "allows an import named Array",
        "avoids collisions between reference names and declaration imports",
        "avoids collisions between references and symbol or enum artifacts",
        "deduplicates imports across definitions and roots",
        "emits every member of a productive mutual cycle",
        "emits unreachable definitions",
        "initializes mixed dependencies and disconnected recursive components in either record order",  # noqa: E501
        "keeps colliding sanitized identifiers distinct",
        "keeps distinct symbols with identical descriptions distinct",
        "keeps generated names from shadowing emitted globals",
        "keeps union combinations compact",
        "orders a diamond dependency once regardless of input order",
        "orders an eager reference in a \x00",
        "orders dependencies passed to a \x00",
        "orders numeric identifiers regardless of reference enumeration",
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
}
