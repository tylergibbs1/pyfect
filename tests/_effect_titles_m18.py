"""Effect 4.1.4 test titles not ported yet (milestone M18, the move from Effect 4.1.2).

Each M18 area ports the titles of its files and deletes them here; an empty ``TITLES`` closes
the milestone. ``tests/_effect_title_omissions.py`` lists every title here as NOT_PORTED.
"""

from __future__ import annotations

M18_REASON = "NOT_PORTED new in Effect 4.1.4 (milestone M18), not ported yet"

TITLES: dict[str, tuple[str, ...]] = {
    "ai/openai-compat/test/OpenAiLanguageModel.test.ts": (
        "rejects PDF URLs before sending a request (\x00)",
    ),
    "ai/openrouter/test/Generated.test.ts": (
        "preserves composed reasoning options",
        "preserves alignment calls in response error metadata",
    ),
    "effect/test/ai/McpServer/McpServer.test.ts": (
        "names tool call spans after the tool and does not record arguments by default",
        "records tool arguments when Toolkit.RecordToolArguments is enabled",
        "continues the client trace from params._meta.traceparent",
        "marks a tool result with isError as a tool_error",
        "records the internal error sent after an error response fails to write",
    ),
}
