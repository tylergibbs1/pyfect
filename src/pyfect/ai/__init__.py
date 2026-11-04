"""AI services (Effect's ``effect/ai``): prompts, responses, tools and
toolkits, the provider-neutral ``LanguageModel`` and ``EmbeddingModel``
services, ``decision`` and the ``DecisionModel`` service (``decision_model``),
the Model Context Protocol (``mcp_server``, ``mcp_client``), and
each provider's structured-output codec (``anthropic_structured_output``,
``openai_structured_output``).

Each module is Effect's of the same name::

    from pyfect.ai import language_model, prompt, response, tool, toolkit
"""

from pyfect.ai import (
    ai_error,
    anthropic_structured_output,
    chat,
    decision,
    decision_model,
    embedding_model,
    id_generator,
    language_model,
    mcp_client,
    mcp_client_error,
    mcp_protocol,
    mcp_schema,
    mcp_server,
    model,
    openai_structured_output,
    prompt,
    response,
    response_id_tracker,
    tokenizer,
    tool,
    toolkit,
)
from pyfect.ai.ai_error import AiError
from pyfect.ai.chat import Chat
from pyfect.ai.decision_model import DecisionModel
from pyfect.ai.language_model import LanguageModel
from pyfect.ai.mcp_client import McpClient
from pyfect.ai.mcp_client_error import McpClientError
from pyfect.ai.mcp_server import McpServer

__all__ = [
    "AiError",
    "Chat",
    "DecisionModel",
    "LanguageModel",
    "McpClient",
    "McpClientError",
    "McpServer",
    "ai_error",
    "anthropic_structured_output",
    "chat",
    "decision",
    "decision_model",
    "embedding_model",
    "id_generator",
    "language_model",
    "mcp_client",
    "mcp_client_error",
    "mcp_protocol",
    "mcp_schema",
    "mcp_server",
    "model",
    "openai_structured_output",
    "prompt",
    "response",
    "response_id_tracker",
    "tokenizer",
    "tool",
    "toolkit",
]
