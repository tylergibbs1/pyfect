"""Effect 4.1.4 test titles not ported yet (milestone M18, the move from Effect 4.1.2).

Each M18 area ports the titles of its files and deletes them here; an empty ``TITLES`` closes
the milestone. ``tests/_effect_title_omissions.py`` lists every title here as NOT_PORTED.
"""

from __future__ import annotations

M18_REASON = "NOT_PORTED new in Effect 4.1.4 (milestone M18), not ported yet"

TITLES: dict[str, tuple[str, ...]] = {
    "ai/anthropic/test/AnthropicLanguageModel.test.ts": (
        "passes tool call params with non-JSON types to the Toolkit",
    ),
    "ai/openai-compat/test/OpenAiLanguageModel.test.ts": (
        "rejects PDF URLs before sending a request (\x00)",
    ),
    "ai/openrouter/test/Generated.test.ts": (
        "preserves composed reasoning options",
        "preserves alignment calls in response error metadata",
    ),
    "effect/test/ai/Chat.test.ts": ("exports tool results with non-JSON types through exportJson",),
    "effect/test/ai/LanguageModel.test.ts": (
        "validates locally handled provider-defined tool parameters in their JSON encoding",
        "validates tool parameters by tool kind when requests share a schema",
    ),
    "effect/test/ai/McpServer/McpServer.test.ts": (
        "names tool call spans after the tool and does not record arguments by default",
        "records tool arguments when Toolkit.RecordToolArguments is enabled",
        "continues the client trace from params._meta.traceparent",
        "marks a tool result with isError as a tool_error",
        "records the internal error sent after an error response fails to write",
    ),
    "effect/test/ai/Response.test.ts": (
        "round trips a Toolkit result with a non-JSON encoding through AllParts JSON",
        "keeps the raw encoding for provider-executed tool results",
    ),
    "effect/test/ai/Tool.test.ts": (
        "decodes parameters from their JSON encoding",
        "encodes results to their JSON encoding",
        "encodes a void result to null",
        "rejects a non-JSON result for a dynamic tool without a success schema",
    ),
}
