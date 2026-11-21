"""Whether a chat history is one the providers take: the next request (the history plus a
user message) is built through each provider's own prompt encoding in the repo, and its
wire form is checked against the provider's rules for tool calls.

- Anthropic Messages: roles alternate, starting with ``user``; each assistant message's
  ``tool_use`` ids are answered by ``tool_result`` blocks that open the next user message,
  each exactly once, and no ``tool_result`` answers anything else.
- OpenAI Responses: each ``function_call`` has exactly one ``function_call_output`` with its
  ``call_id``, after it, and every output answers an earlier call.
- OpenAI Chat Completions (``openai_compat``): an assistant message's ``tool_calls`` are
  followed at once by one ``tool`` message per id, and a ``tool`` message follows only
  those.

``problems`` also checks the history itself: every tool call has exactly one result in the
tool messages after its assistant message, with the same id and name.
"""

from __future__ import annotations

from collections import Counter
from itertools import pairwise
from typing import Any

from pyfect.ai import language_model as lm
from pyfect.ai import prompt as P
from pyfect.ai.anthropic import _prompt as anthropic
from pyfect.ai.openai import _prompt as openai
from pyfect.ai.openai_compat import _prompt as compat
from pyfect.ai.tool import NameMapper

_NAMES = NameMapper(())


def _next_request(history: P.Prompt) -> P.Prompt:
    return history.concat("next")


def _history(history: P.Prompt) -> list[str]:
    found: list[str] = []
    messages = history.content
    for index, message in enumerate(messages):
        if not isinstance(message, P.AssistantMessage):
            continue
        calls = {
            p.id: p.name
            for p in message.content
            if isinstance(p, P.ToolCallPart) and not p.provider_executed
        }
        answers: list[tuple[str, str]] = []
        for later in messages[index + 1 :]:
            if not isinstance(later, P.ToolMessage):
                break
            answers += [(p.id, p.name) for p in later.content if isinstance(p, P.ToolResultPart)]
        counted = Counter(id for id, _ in answers)
        for id, name in calls.items():
            if counted[id] != 1:
                found.append(f"history: call {id} has {counted[id]} results")
            elif (id, name) not in answers:
                found.append(f"history: the result of {id} names another tool")
        found += [f"history: result {id} answers no call" for id in counted if id not in calls]
    return found


def _anthropic(prompt: P.Prompt) -> list[str]:
    prepared = anthropic.prepare_messages(prompt, _NAMES, {}, False)
    messages: list[dict[str, Any]] = prepared.messages
    found: list[str] = []
    roles = [m["role"] for m in messages]
    if roles[:1] != ["user"] or any(a == b for a, b in pairwise(roles)):
        found.append(f"anthropic: roles {roles}")
    for index, message in enumerate(messages):
        blocks: list[dict[str, Any]] = message["content"]
        if not blocks:
            found.append(f"anthropic: message {index} is empty")
        uses = [b["id"] for b in blocks if b["type"] == "tool_use"]
        results = [b["tool_use_id"] for b in blocks if b["type"] == "tool_result"]
        if message["role"] == "user":
            leading = 0
            while leading < len(blocks) and blocks[leading]["type"] == "tool_result":
                leading += 1
            if leading != len(results):
                found.append(f"anthropic: message {index} has a tool_result after other content")
            before = messages[index - 1] if index else None
            asked = (
                []
                if before is None
                else [b["id"] for b in before["content"] if b["type"] == "tool_use"]
            )
            if sorted(results) != sorted(asked):
                found.append(f"anthropic: message {index} answers {results}, asked {asked}")
        if uses and (index + 1 == len(messages) or messages[index + 1]["role"] != "user"):
            found.append(f"anthropic: tool_use {uses} has no user message after it")
    return found


def _openai(prompt: P.Prompt) -> list[str]:
    items = openai.prepare_messages(
        {}, lm.ProviderOptions(prompt), _NAMES, {}, web_socket_mode=False
    )
    found: list[str] = []
    open_calls: set[str] = set()
    answered: Counter[str] = Counter()
    for item in items:
        match item.get("type"):
            case "function_call":
                open_calls.add(item["call_id"])
            case "function_call_output":
                if item["call_id"] not in open_calls:
                    found.append(f"openai: output {item['call_id']} answers no earlier call")
                answered[item["call_id"]] += 1
            case _:
                pass
    found += [
        f"openai: call {id} has {answered[id]} outputs" for id in open_calls if answered[id] != 1
    ]
    return found


def _compat(prompt: P.Prompt) -> list[str]:
    messages = compat.prepare_messages(prompt, {}, _NAMES)
    found: list[str] = []
    waiting: list[str] | None = None
    for index, message in enumerate(messages):
        if message["role"] == "tool":
            if waiting is None or message["tool_call_id"] not in waiting:
                found.append(f"compat: tool message {index} answers no pending call")
            else:
                waiting.remove(message["tool_call_id"])
            continue
        if waiting:
            found.append(f"compat: calls {waiting} unanswered before message {index}")
        calls: list[dict[str, Any]] = message.get("tool_calls") or []
        waiting = [c["id"] for c in calls] if message["role"] == "assistant" else None
    if waiting:
        found.append(f"compat: calls {waiting} unanswered at the end")
    return found


def problems(history: P.Prompt) -> list[str]:
    """What makes ``history`` invalid for a provider's next request (empty: none)."""
    request = _next_request(history)
    return [*_history(history), *_anthropic(request), *_openai(request), *_compat(request)]
