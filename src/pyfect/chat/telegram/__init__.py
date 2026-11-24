"""The Telegram Bot API adapter for ``pyfect.chat`` (Effect's
``@effect/chat-telegram``): ``telegram_chat`` registers the adapter and runs
the webhook or long polling; ``telegram_bot_api`` is the minimal Bot API
client it is built on, for methods the adapter has no op for."""

from pyfect.chat.telegram import telegram_bot_api, telegram_chat
from pyfect.chat.telegram.telegram_bot_api import TelegramBotApi, TelegramChatMigrated
from pyfect.chat.telegram.telegram_chat import (
    ReceiveOptions,
    TelegramChat,
    TelegramChatService,
    TelegramPostOptions,
)

__all__ = [
    "ReceiveOptions",
    "TelegramBotApi",
    "TelegramChat",
    "TelegramChatMigrated",
    "TelegramChatService",
    "TelegramPostOptions",
    "telegram_bot_api",
    "telegram_chat",
]
