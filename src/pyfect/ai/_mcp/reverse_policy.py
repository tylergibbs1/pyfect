"""What a revision lets a server ask its client (Effect's per-revision
``toReverseClient``), past the capability check every operation shares."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from pyfect.ai.mcp_protocol import AnyProtocolAdapter
from pyfect.ai.mcp_schema import (
    ClientCapabilities,
    CreateMessageParams,
    CreateMessageResult,
    ElicitRequestParams,
    JsonObject,
    McpInputRequest,
)

_TOOL_CONTENT = ("tool_use", "tool_result")
_CONTEXTS = ("thisServer", "allServers")


def _has_tool_content(content: object) -> bool:
    blocks = cast("list[object]", content) if isinstance(content, list) else [content]
    return any(
        isinstance(block, dict) and cast("dict[str, object]", block).get("type") in _TOOL_CONTENT
        for block in blocks
    )


def _uses_tools(params: CreateMessageParams) -> bool:
    return (
        "tools" in params
        or "toolChoice" in params
        or any(_has_tool_content(m["content"]) for m in params["messages"])
    )


def sampling_refusal(
    protocol: AnyProtocolAdapter, capabilities: ClientCapabilities, params: CreateMessageParams
) -> str | None:
    """Why ``params`` cannot be sent, if so (Effect's per-revision
    ``createMessage``): 2025-11-25 gates tool use and included context on
    their nested capabilities; before it, requests with either form have no
    wire shape."""
    uses_tools = _uses_tools(params)
    if protocol.supports_icons:
        sampling = capabilities.get("sampling") or {}
        if uses_tools and sampling.get("tools") is None:
            return "Client did not advertise the sampling.tools capability"
        if params.get("includeContext") in _CONTEXTS and sampling.get("context") is None:
            return "Client did not advertise the sampling.context capability"
        return None
    if uses_tools or any(
        isinstance(m["content"], list)
        or (
            not protocol.supports_audio
            and cast("dict[str, object]", m["content"]).get("type") == "audio"
        )
        for m in params["messages"]
    ):
        return "Request is not representable by this protocol"
    return None


def sampling_result_refusal(
    protocol: AnyProtocolAdapter, capabilities: ClientCapabilities, result: CreateMessageResult
) -> str | None:
    """2025-11-25: a client that did not advertise ``sampling.tools`` must
    not answer with tool use."""
    if not protocol.supports_icons:
        return None
    sampling = capabilities.get("sampling") or {}
    uses_tools = result.get("stopReason") == "toolUse" or _has_tool_content(result["content"])
    if uses_tools and sampling.get("tools") is None:
        return "Client did not advertise the sampling.tools capability"
    return None


def project_elicitation(
    protocol: AnyProtocolAdapter, capabilities: ClientCapabilities, params: ElicitRequestParams
) -> ElicitRequestParams | str:
    """``params`` as ``protocol`` sends them, or why it cannot (Effect's
    per-revision ``elicit``): 2025-11-25 gates each mode on its nested
    capability (an empty one is form support); 2025-06-18 has form mode
    only, sent without its ``mode``."""
    url = params.get("mode") == "url"
    if protocol.supports_icons:
        elicitation = capabilities.get("elicitation") or {}
        supported = (
            "url" in elicitation if url else "form" in elicitation or "url" not in elicitation
        )
        if not supported:
            mode = "url" if url else "form"
            return f"Client did not advertise the elicitation.{mode} capability"
        return params
    if url:
        return "Request is not representable by this protocol"
    return cast("ElicitRequestParams", {k: v for k, v in params.items() if k != "mode"})


def required_input_capabilities(
    requests: Mapping[str, McpInputRequest] | None, capabilities: ClientCapabilities
) -> dict[str, JsonObject]:
    """The client capabilities ``requests`` need that the client did not
    declare (Effect's ``requiredCapabilitiesForInputRequests``)."""
    required: dict[str, JsonObject] = {}
    for request in (requests or {}).values():
        if request["method"] == "roots/list":
            if capabilities.get("roots") is None:
                required["roots"] = {}
        elif request["method"] == "sampling/createMessage":
            params = request["params"]
            advertised = capabilities.get("sampling")
            sampling = required.get("sampling", {})
            if _uses_tools(params) and (advertised or {}).get("tools") is None:
                sampling["tools"] = {}
            if (
                params.get("includeContext") in _CONTEXTS
                and (advertised or {}).get("context") is None
            ):
                sampling["context"] = {}
            if advertised is None or sampling:
                required["sampling"] = sampling
        else:
            mode = "url" if request["params"].get("mode") == "url" else "form"
            elicitation = capabilities.get("elicitation")
            supported = elicitation is not None and (
                elicitation.get("url") is not None
                if mode == "url"
                else elicitation.get("form") is not None or not elicitation
            )
            if not supported:
                required.setdefault("elicitation", {})[mode] = {}
    return required
