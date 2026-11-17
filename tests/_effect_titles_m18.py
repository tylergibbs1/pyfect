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
    "effect/test/TestClock.test.ts": ("serializes a context containing a TestClock",),
    "effect/test/Tracer.test.ts": ("leaves an empty cause Unset without a description",),
    "effect/test/ai/AgUi.test.ts": (
        "drops client system, developer and context instructions by default",
        "keeps client system and developer messages in place when trusted",
        "keeps the failure marker of tool results emitted by fromStreamParts",
        "names each tool result after the latest preceding call with its id",
        "maps each model round to a step of AG-UI events",
        "opens the run and closes anything left open before finishing",
        "ends a failed run with a single RUN_ERROR",
        "tracks steps per subagent and closes subagents left running",
    ),
    "effect/test/ai/AgUiSchema.test.ts": (
        "drops unrecognised union members",
        "drops entries whose closed-set values are unrecognised",
        "rejects a malformed recognised union member",
    ),
    "effect/test/ai/AgUiServer.test.ts": (
        "streams a run hook's events as AG-UI server-sent events",
        "serves the run overload when an undefined agent property is present",
        "rejects an invalid RunAgentInput before opening the stream",
        "reports a failing run hook as RUN_ERROR",
        "reports an event that cannot be encoded as RUN_ERROR",
        "reports an event that is invalid once serialized as RUN_ERROR",
        "never serializes an event outside the run's error handling",
        "runs the model with server tools until it answers",
        "finishes with the frontend tool calls left for the application",
        "lists calls to client-executed toolkit tools as pending",
        "serves an agent from an endpoint in an existing HttpApi",
        "rejects a frontend tool that shadows a server tool before the stream opens",
        "documents the item schemas of the run input in OpenAPI",
    ),
    "effect/test/ai/Chat.test.ts": (
        "continues with tool results until a round needs no tools",
        "runs one round by default and at most maxSteps rounds",
        "stops when a client-executed tool call is left for the application",
        "exports tool results with non-JSON types through exportJson",
    ),
    "effect/test/ai/LanguageModel.test.ts": (
        "\x00 leaves client-executed tool calls unresolved",
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
    "effect/test/observability/OtlpTracer.test.ts": ("leaves $name status Unset",),
    "opentelemetry/test/OtelTracer.test.ts": ("keeps the status of $name",),
}
