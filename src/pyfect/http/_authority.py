"""The authority of a request URL (``host[:port]``), checked once where a
server reads it from the client (``Host``, an absolute-form target,
``X-Forwarded-Host``). A request's absolute URL is built only from an
``Authority`` and an ``OriginForm``, so nothing a client sends as a host
or a target can become part of the other."""

from __future__ import annotations

import re
from typing import NewType

from pyfect._url import Url

Authority = NewType("Authority", str)
"""A ``host[:port]``: a bracketed IP literal or a name of letters, digits,
``.``, ``-`` and ``_``, and a port up to 65535."""

_SHAPE = re.compile(r"(?:\[[0-9A-Fa-f:.]+\]|[A-Za-z0-9._-]+)(?::[0-9]{1,5})?")


def parse_authority(text: str) -> Authority | None:
    """``text`` as an authority; ``None`` for anything else (a path, query
    or fragment, userinfo, a list, a bad IP literal or port). As Effect's
    ``isValidHost``, the shape rules out paths, userinfo and lists and the
    URL parser rejects bad IP literals and ports."""
    if _SHAPE.fullmatch(text) is None or not Url.can_parse(f"http://{text}"):
        return None
    return Authority(text)


LOCALHOST = Authority("localhost")
"""The authority of a request that names none."""

OriginForm = NewType("OriginForm", str)
"""A path and query that starts with ``/`` (RFC 9112's origin-form)."""

ROOT = OriginForm("/")


def parse_origin_form(target: str) -> OriginForm | None:
    """``target`` as a path and query; ``None`` without a leading ``/``
    (``admin``, ``evil.test/admin``), which would run into the authority
    or route somewhere a front end did not see."""
    return OriginForm(target) if target.startswith("/") else None


def absolute_url(scheme: str, authority: Authority, target: OriginForm) -> str:
    """The URL of ``target`` at ``authority``."""
    return f"{scheme}://{authority}{target}"


__all__ = [
    "LOCALHOST",
    "ROOT",
    "Authority",
    "OriginForm",
    "absolute_url",
    "parse_authority",
    "parse_origin_form",
]
