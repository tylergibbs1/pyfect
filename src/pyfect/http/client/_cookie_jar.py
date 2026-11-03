"""The RFC 6265 matching ``with_cookies_ref`` applies to its ``Cookies``.

A cookie a response sets is bound to where it came from: its ``Domain``
(which must cover the responding host) or else the responding host, and its
``Path`` (or the directory of the request path). It is sent back only to a
matching host and path, and only over https when it is ``Secure``. A
response may not set a cookie for a domain it does not belong to or for a
whole top-level domain, nor
replace a cookie bound to a domain it does not belong to. Cookies the
program put in the jar without a ``Domain`` are its own, and go to every
request.
"""

from __future__ import annotations

import ipaddress
from dataclasses import replace
from urllib.parse import SplitResult

from pyfect.http import url as _url
from pyfect.http.cookies import Cookie, CookieOptions, Cookies


def _where(url: str) -> _url.Url | None:
    try:
        return _url.parse(url)
    except ValueError:
        return None


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def _domain_match(host: str, domain: str) -> bool:
    domain = domain.lower()
    return host == domain or (host.endswith(f".{domain}") and not _is_ip(host))


def _may_set_domain(host: str, domain: str) -> bool:
    """Whether a response from ``host`` may set a cookie for ``domain``: one
    covering it, and not a whole top-level domain (``Domain=com``) unless
    that is the host itself. Without a public suffix list, ``co.uk``-style
    suffixes are not caught."""
    return host == domain or ("." in domain and _domain_match(host, domain))


def _path_match(path: str, cookie_path: str) -> bool:
    return (
        path == cookie_path
        or (path.startswith(cookie_path) and cookie_path.endswith("/"))
        or path.startswith(f"{cookie_path}/")
    )


def _default_path(path: str) -> str:
    if not path.startswith("/") or path.count("/") == 1:
        return "/"
    return path[: path.rindex("/")]


def _options(cookie: Cookie) -> CookieOptions:
    return cookie.options or CookieOptions()


def _bound(cookie: Cookie, url: SplitResult) -> Cookie | None:
    """``cookie`` as set by a response from ``url``: bound to its host and
    path, or ``None`` when that response may not set it."""
    host = (url.hostname or "").lower()
    options = _options(cookie)
    if options.domain is not None and not _may_set_domain(host, options.domain.lower()):
        return None
    if options.secure and url.scheme != "https":
        return None
    return replace(
        cookie,
        options=replace(
            options,
            domain=options.domain or host,
            path=options.path or _default_path(url.path or "/"),
        ),
    )


def store(jar: Cookies, response_url: str, received: Cookies) -> Cookies:
    """``jar`` with the cookies a response from ``response_url`` set."""
    url = _where(response_url)
    if url is None or received.is_empty():
        return jar
    host = (url.hostname or "").lower()
    accepted: list[Cookie] = []
    for cookie in received:
        bound = _bound(cookie, url)
        held = jar.get(cookie.name)
        held_domain = None if held is None else _options(held).domain
        if bound is not None and (held_domain is None or _domain_match(host, held_domain)):
            accepted.append(bound)
    return jar.set_all_cookie(accepted)


def for_request(jar: Cookies, request_url: str) -> Cookies:
    """The cookies of ``jar`` that go with a request to ``request_url``."""
    url = _where(request_url)
    host = "" if url is None else (url.hostname or "").lower()
    path = "/" if url is None else url.path or "/"
    secure = url is not None and url.scheme == "https"

    def sent(cookie: Cookie) -> bool:
        options = _options(cookie)
        return (
            (options.domain is None or _domain_match(host, options.domain))
            and (options.path is None or _path_match(path, options.path))
            and (secure or not options.secure)
        )

    return Cookies({cookie.name: cookie for cookie in jar if sent(cookie)})
