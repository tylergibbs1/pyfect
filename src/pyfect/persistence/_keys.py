"""Key namespaces of the persistence stores (Effect's
``internal/persistence.ts``)."""

from __future__ import annotations

import re

_REDIS_GLOB_SPECIAL = re.compile(r"[\\*?\[\]]")


def escape_key_segment(segment: str) -> str:
    """``segment`` with ``%`` and ``:`` percent-encoded, so it holds no
    ``:`` and distinct segments stay distinct."""
    return segment.replace("%", "%25").replace(":", "%3A")


def store_namespace(store_id: str) -> str:
    """The key prefix of store ``store_id``: it ends at its first ``:``, so
    distinct store / key pairs never spell the same key."""
    return f"{escape_key_segment(store_id)}:"


def escape_redis_glob(pattern: str) -> str:
    """``pattern`` matching itself literally in a Redis ``KEYS`` / ``SCAN``
    glob."""
    return _REDIS_GLOB_SPECIAL.sub(lambda match: "\\" + match.group(), pattern)
