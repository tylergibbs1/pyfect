"""A Messages response as encoded response parts (Effect's
``makeResponse``), and what it shares with the streamed one: finish
reasons, citations, tool-call parameters and server tool results."""

from __future__ import annotations

from collections.abc import Callable, Generator, Iterator
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

import pyfect as fx
from pyfect import date_time
from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai import _provider_tools as PT
from pyfect.ai import language_model as lm
from pyfect.ai import prompt as Pr
from pyfect.ai.ai_error import AiError
from pyfect.ai.anthropic import _schema as W
from pyfect.ai.anthropic._prompt import is_citation_part
from pyfect.ai.anthropic._tools import to_codec_lenient
from pyfect.ai.id_generator import IdGenerator
from pyfect.ai.response import FinishReason
from pyfect.ai.tool import NameMapper
from pyfect.http.response import HttpClientResponse

type Part = dict[str, Any]
type Gen[A] = Generator[Effect[Any, AiError, Any], Any, A]

_FINISH_REASONS: dict[str, FinishReason] = {
    "end_turn": "stop",
    "max_tokens": "length",
    "model_context_window_exceeded": "length",
    "pause_turn": "pause",
    "refusal": "content-filter",
    "stop_sequence": "stop",
    "tool_use": "tool-calls",
}


def resolve_finish_reason(reason: str, is_json_response: bool = False) -> FinishReason:
    resolved = _FINISH_REASONS.get(reason, "unknown")
    return "stop" if is_json_response and resolved == "tool-calls" else resolved


@dataclass
class CitableDocument:
    title: str
    media_type: str
    file_name: str | None = None


def _citable_parts(prompt: Pr.Prompt) -> Iterator[object]:
    """User parts and tool results' model output, in prompt order."""
    for message in prompt.content:
        if isinstance(message, Pr.UserMessage):
            yield from message.content
        elif isinstance(message, Pr.ToolMessage):
            for part in message.content:
                if isinstance(part, Pr.ToolResultPart) and part.model_output is not None:
                    yield from part.model_output


def citable_documents(prompt: Pr.Prompt) -> list[CitableDocument]:
    return [
        CitableDocument(
            P.or_default(part.file_name, "Untitled Document"), part.media_type, part.file_name
        )
        for part in _citable_parts(prompt)
        if isinstance(part, Pr.FilePart) and is_citation_part(part)
    ]


def now_iso() -> Effect[str]:
    return date_time.now().map(date_time.format_iso)


def generate_id() -> Effect[str, Any, IdGenerator]:
    return IdGenerator().flat_map(lambda ids: ids.generate_id())


def citation_source(citation: dict[str, Any], documents: list[CitableDocument]) -> Gen[Part | None]:
    """The source part of a citation, if it names a known document or a
    web result (Effect's ``processCitation``)."""
    kind = citation.get("type")
    if kind in ("page_location", "char_location"):
        index: int = citation.get("document_index", -1)
        if not 0 <= index < len(documents):
            return None
        document = documents[index]
        id = yield from generate_id()
        if kind == "char_location":
            location = {
                "startCharIndex": citation.get("start_char_index"),
                "endCharIndex": citation.get("end_char_index"),
            }
        else:
            location = {
                "startPageNumber": citation.get("start_page_number"),
                "endPageNumber": citation.get("end_page_number"),
            }
        source: Part = {
            "type": "source",
            "sourceType": "document",
            "id": id,
            "mediaType": document.media_type,
            "title": P.or_default(citation.get("document_title"), document.title),
            "metadata": {
                "anthropic": {
                    "source": "document",
                    "type": kind,
                    "citedText": citation.get("cited_text"),
                    **location,
                }
            },
        }
        if document.file_name is not None:
            source["fileName"] = document.file_name
        return source
    if kind == "web_search_result_location":
        id = yield from generate_id()
        return {
            "type": "source",
            "sourceType": "url",
            "id": id,
            "url": citation.get("url"),
            "title": P.or_default(citation.get("title"), "Untitled"),
            "metadata": {
                "anthropic": {
                    "source": "url",
                    "citedText": citation.get("cited_text"),
                    "encryptedIndex": citation.get("encrypted_index"),
                }
            },
        }
    return None


def transform_params(
    options: lm.ProviderOptions, tool_name: str, params: object
) -> Effect[object, AiError, Any]:
    """A non-strict tool's request used the plain JSON Schema when
    Anthropic's codec rejected its parameters, so its calls decode with the
    plain codec too."""
    return PT.transform_params(
        "AnthropicLanguageModel", options, tool_name, params, transformer=to_codec_lenient
    )


def server_tool_result(id: str, name: str, is_failure: bool, result: object) -> Part:
    """A result the server produced in the assistant turn (code execution,
    MCP, tool search, web fetch and search), replayed there by
    ``Prompt.from_response_parts``. Effect 4.1.2 leaves ``providerExecuted``
    off the code execution, MCP and web fetch results, so a chat replays them
    as user ``tool_result`` blocks, which Anthropic rejects."""
    return {
        "type": "tool-result",
        "id": id,
        "name": name,
        "isFailure": is_failure,
        "result": result,
        "providerExecuted": True,
    }


def provider_tool_name(server_tool: str) -> str:
    """The provider-defined tool a ``server_tool_use`` name belongs to:
    code execution's ``bash_code_execution`` and ``text_editor_code_execution``
    sub-tools are calls of ``code_execution`` (as Effect's stream decoder
    names them; its non-streaming decoder leaves them unmapped, so the call
    matches no tool)."""
    return "code_execution" if server_tool.endswith("_code_execution") else server_tool


type ServerResultBlock = Literal[
    "mcp_tool_result",
    "code_execution_tool_result",
    "bash_code_execution_tool_result",
    "text_editor_code_execution_tool_result",
    "tool_search_tool_result",
    "web_fetch_tool_result",
    "web_search_tool_result",
]
SERVER_RESULT_BLOCKS: tuple[ServerResultBlock, ...] = get_args(ServerResultBlock.__value__)


@dataclass
class ServerResults:
    """What server tool results need across a response: the citable
    documents, MCP calls and tool-search calls seen so far."""

    names: NameMapper
    documents: list[CitableDocument]
    mcp_calls: dict[str, Part] = field(default_factory=dict[str, Part])
    search_calls: dict[str, str] = field(default_factory=dict[str, str])

    def mcp_call(self, block: W.ContentBlock) -> Part:
        call: Part = {
            "type": "tool-call",
            "id": block["id"],
            "name": block["name"],
            "params": block.get("input"),
            "providerExecuted": True,
            "metadata": {"anthropic": {"mcp_tool": {"server": block.get("server_name")}}},
        }
        self.mcp_calls[block["id"]] = call
        return call

    def mcp_result(self, block: W.ContentBlock) -> list[Part]:
        call = self.mcp_calls.get(block["tool_use_id"])
        if call is None:
            return []
        server = call["metadata"]["anthropic"]["mcp_tool"]
        part = server_tool_result(
            block["tool_use_id"], call["name"], block.get("is_error", False), block.get("content")
        )
        part["metadata"] = {"anthropic": {"mcp_tool": server}}
        return [part]

    def code_execution(self, block: W.ContentBlock) -> list[Part]:
        content = P.obj(block.get("content"))
        if block["type"] == "code_execution_tool_result":
            failed = content.get("type") != "code_execution_result"
        else:
            failed = content.get("type") in (
                "bash_code_execution_tool_result_error",
                "text_editor_code_execution_tool_result_error",
            )
        name = self.names.get_custom_name("code_execution")
        return [server_tool_result(block["tool_use_id"], name, failed, content)]

    def tool_search(self, block: W.ContentBlock) -> list[Part]:
        provider = self.search_calls.get(block["tool_use_id"])
        if provider is None:
            if self.names.get_custom_name("tool_search_tool_bm25") != "tool_search_tool_bm25":
                provider = "tool_search_tool_bm25"
            elif self.names.get_custom_name("tool_search_tool_regex") != "tool_search_tool_regex":
                provider = "tool_search_tool_regex"
        name = self.names.get_custom_name(provider or "undefined")
        content = P.obj(block.get("content"))
        if content.get("type") == "tool_search_tool_search_result":
            references = content.get("tool_references")
            return [server_tool_result(block["tool_use_id"], name, False, references)]
        return [server_tool_result(block["tool_use_id"], name, True, content)]

    def web_fetch(self, block: W.ContentBlock) -> list[Part]:
        name = self.names.get_custom_name("web_fetch")
        content = P.obj(block.get("content"))
        if content.get("type") == "web_fetch_result":
            document = P.obj(content.get("content"))
            self.documents.append(
                CitableDocument(
                    P.or_default(document.get("title"), content.get("url") or ""),
                    P.obj(document.get("source")).get("media_type") or "",
                )
            )
            return [server_tool_result(block["tool_use_id"], name, False, content)]
        return [server_tool_result(block["tool_use_id"], name, True, content)]

    def web_search(self, block: W.ContentBlock) -> Gen[list[Part]]:
        name = self.names.get_custom_name("web_search")
        content: object = block.get("content")
        error = P.obj(content)
        if "type" in error:
            return [server_tool_result(block["tool_use_id"], name, True, error)]
        results = P.arr(content)
        parts = [server_tool_result(block["tool_use_id"], name, False, results)]
        for result in results:
            id = yield from generate_id()
            parts.append(
                {
                    "type": "source",
                    "sourceType": "url",
                    "id": id,
                    "url": result.get("url"),
                    "title": result.get("title"),
                    "metadata": {"anthropic": {"source": "web", "pageAge": result.get("page_age")}},
                }
            )
        return parts

    def result_parts(self, block: W.ContentBlock) -> Gen[list[Part] | None]:
        """The parts of a server tool result block, ``None`` for another
        block."""
        handlers: dict[ServerResultBlock, Callable[[W.ContentBlock], list[Part]]] = {
            "mcp_tool_result": self.mcp_result,
            "code_execution_tool_result": self.code_execution,
            "bash_code_execution_tool_result": self.code_execution,
            "text_editor_code_execution_tool_result": self.code_execution,
            "tool_search_tool_result": self.tool_search,
            "web_fetch_tool_result": self.web_fetch,
        }
        handler = handlers.get(block["type"])
        if handler is not None:
            return handler(block)
        if block["type"] == "web_search_tool_result":
            return (yield from self.web_search(block))
        return None


def caller_metadata(block: W.ContentBlock) -> dict[str, Any] | None:
    caller = P.obj(block.get("caller"))
    if not caller:
        return None
    return {"type": caller.get("type"), "toolId": caller.get("tool_id")}


def usage_part(
    input_tokens: int, output_tokens: int, cache_read: int, cache_write: int
) -> dict[str, Any]:
    return {
        "inputTokens": {
            "uncached": input_tokens,
            "total": input_tokens + cache_write + cache_read,
            "cacheRead": cache_read,
            "cacheWrite": cache_write,
        },
        "outputTokens": {"total": output_tokens},
    }


# Generated responses --------------------------------------------------------------------


@dataclass
class _Response:
    options: lm.ProviderOptions
    message: W.Message
    response: HttpClientResponse
    results: ServerResults
    timestamp: str
    parts: list[Part] = field(default_factory=list[Part])

    @property
    def json_format(self) -> lm.JsonFormat | None:
        format = self.options.response_format
        return format if isinstance(format, lm.JsonFormat) else None

    def has_response_tool(self) -> bool:
        format = self.json_format
        return format is not None and any(
            block["type"] == "tool_use" and block.get("name") == format.object_name
            for block in self.message["content"]
        )

    def text(self, block: W.ContentBlock, skip: bool) -> Gen[None]:
        if skip:
            return
        self.parts.append({"type": "text", "text": block.get("text", "")})
        for citation in P.arr(block.get("citations")):
            source = yield from citation_source(citation, self.results.documents)
            if source is not None:
                self.parts.append(source)

    def tool_use(self, block: W.ContentBlock) -> Gen[None]:
        format = self.json_format
        if format is not None and block.get("name") == format.object_name:
            self.parts.append({"type": "text", "text": P.dumps(block.get("input"))})
            return
        name = self.results.names.get_custom_name(block["name"])
        params = yield from transform_params(self.options, name, block.get("input"))
        part: Part = {"type": "tool-call", "id": block["id"], "name": name, "params": params}
        caller = caller_metadata(block)
        if caller is not None:
            part["metadata"] = {"anthropic": {"caller": caller}}
        self.parts.append(part)

    def server_tool_use(self, block: W.ContentBlock) -> None:
        provider = block["name"]
        name = self.results.names.get_custom_name(provider_tool_name(provider))
        input = P.obj(block.get("input"))
        if provider in ("bash_code_execution", "text_editor_code_execution"):
            params: dict[str, Any] = {"type": provider, **input}
        elif provider in ("code_execution", "web_fetch", "web_search"):
            params = input
            if provider == "code_execution" and "code" in input and "type" not in input:
                params = {**input, "type": "programmatic-tool-call"}
        elif provider in ("tool_search_tool_bm25", "tool_search_tool_regex"):
            self.results.search_calls[block["id"]] = provider
            params = input
        else:
            return
        self.parts.append(
            {
                "type": "tool-call",
                "id": block["id"],
                "name": name,
                "params": params,
                "providerExecuted": True,
            }
        )

    def reasoning(self, block: W.ContentBlock) -> None:
        if block["type"] == "thinking":
            info = {"type": "thinking", "signature": block.get("signature")}
            text = block.get("thinking", "")
        else:
            info = {"type": "redacted_thinking", "redactedData": block.get("data")}
            text = ""
        self.parts.append(
            {"type": "reasoning", "text": text, "metadata": {"anthropic": {"info": info}}}
        )

    def block(self, block: W.ContentBlock, skip_text: bool) -> Gen[None]:
        match block["type"]:
            case "fallback":
                self.parts.append(
                    {
                        "type": "response-metadata",
                        "modelId": block["to"]["model"],
                        "timestamp": self.timestamp,
                        "metadata": {"anthropic": {"fallback": block}},
                    }
                )
            case "text":
                yield from self.text(block, skip_text)
            case "thinking" | "redacted_thinking":
                self.reasoning(block)
            case "tool_use":
                yield from self.tool_use(block)
            case "server_tool_use":
                self.server_tool_use(block)
            case "mcp_tool_use":
                self.parts.append(self.results.mcp_call(block))
            case _:
                parts = yield from self.results.result_parts(block)
                self.parts.extend(parts or [])

    def finish(self) -> Part:
        message = self.message
        usage = message["usage"]
        return {
            "type": "finish",
            "reason": resolve_finish_reason(
                message["stop_reason"] or "", self.json_format is not None
            ),
            "usage": usage_part(
                usage["input_tokens"],
                usage["output_tokens"],
                usage.get("cache_read_input_tokens") or 0,
                usage.get("cache_creation_input_tokens") or 0,
            ),
            "response": P.response_details(self.response),
            "metadata": {
                "anthropic": {
                    "container": message.get("container"),
                    "contextManagement": message.get("context_management"),
                    "usage": usage,
                    "stopSequence": message["stop_sequence"],
                }
            },
        }

    def run(self) -> Gen[list[Part]]:
        self.parts.append(
            {
                "type": "response-metadata",
                "id": self.message["id"],
                "modelId": self.message["model"],
                "timestamp": self.timestamp,
            }
        )
        skip_text = self.has_response_tool()
        for block in self.message["content"]:
            yield from self.block(block, skip_text)
        self.parts.append(self.finish())
        return self.parts


def make_response(
    options: lm.ProviderOptions,
    message: W.Message,
    response: HttpClientResponse,
    names: NameMapper,
) -> Effect[list[Part], AiError, Any]:
    results = ServerResults(names, citable_documents(options.prompt))
    return now_iso().flat_map(
        lambda timestamp: fx.gen(
            lambda: _Response(options, message, response, results, timestamp).run()
        )
    )
