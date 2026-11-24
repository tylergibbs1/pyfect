"""The scoped WhatsApp post options."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace

from pyfect.context import Reference

DEFAULT_LIST_BUTTON = "Options"
DEFAULT_BUTTONS_SECTION = "Actions"


@dataclass(frozen=True, kw_only=True)
class WhatsAppPostOptions:
    """WhatsApp options for every write inside an effect; ``None`` leaves a
    field as the enclosing options set it.

    - ``link_preview``: a preview of the first link in a text message.
      Default false.
    - ``list_button``: the button that opens a list, when no select has a
      placeholder. Default ``"Options"``, up to 20.
    - ``buttons_section``: the title of a list's buttons section beside a
      select. Default ``"Actions"``, up to 24.
    """

    link_preview: bool | None = None
    list_button: str | None = None
    buttons_section: str | None = None

    def merge(self, inner: WhatsAppPostOptions) -> WhatsAppPostOptions:
        """These options with ``inner``'s set fields winning."""
        changes: dict[str, object] = {
            field.name: value
            for field in fields(inner)
            if (value := getattr(inner, field.name)) is not None
        }
        return replace(self, **changes)


class CurrentPostOptions(
    Reference[WhatsAppPostOptions], key="@effect/chat-whatsapp/CurrentPostOptions"
):
    """The WhatsApp post options in scope."""

    @classmethod
    def default(cls) -> WhatsAppPostOptions:
        return WhatsAppPostOptions()
