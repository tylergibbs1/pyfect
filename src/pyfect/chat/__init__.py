"""Chat platforms behind one interface (Effect's ``effect/chat``): the
``Chat`` service that posts, edits and streams to any registered adapter
(``chat``, ``chat_adapter``), the values it speaks in (``chat_thread``,
``chat_message``, ``chat_event``, ``chat_ui``, ``chat_error``), typed buttons,
selects, modals and slash commands (``chat_interaction``), the event handler
(``chat_handler``), Markdown replies split to fit a platform's limits and
streamed as they are written (``chat_markdown``), and an in-memory platform
with a conformance suite for adapters (``chat_test``).

Each module is Effect's of the same name::

    from pyfect.chat import chat, chat_markdown, chat_test
"""

from pyfect.chat import (
    chat,
    chat_adapter,
    chat_error,
    chat_event,
    chat_handler,
    chat_interaction,
    chat_markdown,
    chat_message,
    chat_test,
    chat_thread,
    chat_ui,
)
from pyfect.chat.chat import Chat
from pyfect.chat.chat_error import ChatError
from pyfect.chat.chat_test import ChatTest

__all__ = [
    "Chat",
    "ChatError",
    "ChatTest",
    "chat",
    "chat_adapter",
    "chat_error",
    "chat_event",
    "chat_handler",
    "chat_interaction",
    "chat_markdown",
    "chat_message",
    "chat_test",
    "chat_thread",
    "chat_ui",
]
