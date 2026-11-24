"""The WhatsApp Cloud API adapter for ``pyfect.chat`` (Effect's
``@effect/chat-whatsapp``): ``whatsapp_chat`` registers the adapter and serves
the webhook; ``whatsapp_graph_api`` is the minimal Graph API client it is built
on, for endpoints the adapter has no op for; ``whatsapp_update`` holds the
statuses and id changes that come beside messages."""

from pyfect.chat.whatsapp import whatsapp_chat, whatsapp_graph_api, whatsapp_update
from pyfect.chat.whatsapp.whatsapp_chat import (
    Template,
    WhatsAppChat,
    WhatsAppChatService,
    WhatsAppPostOptions,
)
from pyfect.chat.whatsapp.whatsapp_graph_api import WhatsAppGraphApi
from pyfect.chat.whatsapp.whatsapp_update import WhatsAppUpdate

__all__ = [
    "Template",
    "WhatsAppChat",
    "WhatsAppChatService",
    "WhatsAppGraphApi",
    "WhatsAppPostOptions",
    "WhatsAppUpdate",
    "whatsapp_chat",
    "whatsapp_graph_api",
    "whatsapp_update",
]
