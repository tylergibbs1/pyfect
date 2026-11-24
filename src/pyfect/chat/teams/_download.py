"""Files on inbound messages: an attachment's id, and the download behind it.

An attachment id is one of:

- ``connector:{url}``: a Connector attachment view, fetched with the bot token.
- ``preauth:{url}``: a pre-authenticated file URL, fetched with no
  credentials. The URL itself grants access, so it is never logged.
- ``url:{url}``: any other URL. It is kept so the message shows the file,
  but ``download`` refuses it.
"""

from __future__ import annotations

import re
from collections.abc import Generator, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from typing import Any, Literal, Never

import pyfect as fx
from pyfect import stream as _stream
from pyfect._core import Effect
from pyfect._url import Url
from pyfect.chat.chat_error import ChatError
from pyfect.chat.chat_message import Attachment
from pyfect.chat.teams import _errors, _json
from pyfect.http import request as http_request
from pyfect.http.client import HttpClientService, TracerDisabledWhen
from pyfect.http.error import HttpClientError
from pyfect.http.httpx_client import FollowRedirects
from pyfect.http.response import HttpClientResponse
from pyfect.http.url import set_hash
from pyfect.redacted import Redacted
from pyfect.stream import Stream
from pyfect.tracer._spans import annotate_current_span

_OP = "download"

FILE_DOWNLOAD_INFO = "application/vnd.microsoft.teams.file.download.info"
"""The content type of a personal chat file the bot may fetch without credentials."""

type Kind = Literal["connector", "preauth", "url"]

_KINDS: tuple[Kind, ...] = ("connector", "preauth", "url")

CONNECTOR_PATH = re.compile(
    r"(?:/[A-Za-z0-9_-]+)?/v3/attachments/[A-Za-z0-9_-]+/views/[A-Za-z0-9_-]+"
)
"""The path of a Connector attachment view,
``/{region}/v3/attachments/{id}/views/{view}``, where the region segment may
be absent; matched whole."""

MAX_REDIRECTS = 3
"""The most redirects one download follows."""

_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_IPV4 = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+")


def under_suffix(host: str, suffixes: Sequence[str]) -> bool:
    """Whether ``host`` is a suffix or ends with ``.{suffix}``."""
    for raw in suffixes:
        suffix = raw.lower().removeprefix(".")
        if suffix and (host == suffix or host.endswith(f".{suffix}")):
            return True
    return False


def _is_ip_literal(host: str) -> bool:
    return host.startswith("[") or _IPV4.fullmatch(host) is not None


def safe_url(input: str, base: str | None = None) -> Url | None:
    """Parses ``input`` and checks the parts every hop needs: ``https:``, no
    userinfo, the default port and a host name rather than an IP literal.
    The fragment is dropped, since it is never sent."""
    url = Url.parse(input, base)
    if (
        url is None
        or url.protocol != "https:"
        or url.username
        or url.password
        or url.port
        or not url.hostname
        or _is_ip_literal(url.hostname)
    ):
        return None
    return set_hash(url, "")


def _size(record: _json.JsonObject) -> int | None:
    value = record.get("size")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    number = int(value)
    return number if 0 <= number <= 2**53 - 1 else None


def classify(
    attachment: object,
    *,
    service_url: str,
    conversation_type: str | None,
    connector_hosts: AbstractSet[str],
    file_host_suffixes: Sequence[str],
) -> Attachment | None:
    """A Bot Framework activity attachment as a chat attachment.

    - ``connector:`` when ``contentUrl`` has the origin of the activity's
      ``serviceUrl``, its host is in ``connector_hosts`` and its path is
      ``CONNECTOR_PATH``.
    - ``preauth:`` for a file download info attachment in a personal chat
      whose ``content.downloadUrl`` is under one of ``file_host_suffixes``.
      Its ``contentType`` is Teams' own, so it is left out.
    - ``url:`` for any other ``https:`` or ``http:`` ``contentUrl``.

    An attachment with no usable URL, such as a card, is ``None``."""
    record = _json.as_object(attachment)
    if record is None:
        return None
    content_type = _json.string(record, "contentType")
    name = _json.string(record, "name")
    content = _json.object_(record, "content")

    def make(id: str, type: str | None, size: int | None) -> Attachment:
        return Attachment(id=id, name=name, content_type=type, size=size)

    if (
        content_type == FILE_DOWNLOAD_INFO
        and conversation_type == "personal"
        and content is not None
    ):
        raw = _json.string(content, "downloadUrl")
        url = None if raw is None else safe_url(raw)
        if url is not None and under_suffix(url.hostname, file_host_suffixes):
            size = _size(content)
            return make(f"preauth:{url.href}", None, _size(record) if size is None else size)

    raw = _json.string(record, "contentUrl")
    if raw is None:
        return None
    type = None if content_type == FILE_DOWNLOAD_INFO else content_type
    url = safe_url(raw)
    service = Url.parse(service_url)
    if (
        url is not None
        and service is not None
        and url.origin == service.origin
        and url.hostname in connector_hosts
        and not url.search
        and CONNECTOR_PATH.fullmatch(url.pathname) is not None
    ):
        return make(f"connector:{url.href}", type, _size(record))
    other = Url.parse(raw)
    if other is None or other.protocol not in ("https:", "http:"):
        return None
    return make(f"url:{other.href}", type, _size(record))


def parse_id(id: str) -> tuple[Kind, str] | None:
    """An attachment id's kind and URL."""
    kind, colon, url = id.partition(":")
    if not colon:
        return None
    for known in _KINDS:
        if known == kind:
            return known, url
    return None


@dataclass(frozen=True, kw_only=True)
class DownloadOptions:
    """``token`` is read only for a ``connector:`` id, and sent on its first
    request only. ``connector_hosts`` are exact hosts, ``file_host_suffixes``
    match at a label boundary, and ``redirect_hosts`` are exact hosts a
    redirect may also go to."""

    max_bytes: int
    token: Effect[Redacted[str], ChatError]
    connector_hosts: AbstractSet[str]
    file_host_suffixes: Sequence[str]
    http: HttpClientService[HttpClientError, Never]
    redirect_hosts: AbstractSet[str] = field(default_factory=frozenset[str])


def _fail(reason: Any) -> Effect[Never, ChatError]:
    return fx.fail(_errors.chat_error(_OP, reason))


def _no_trace(_request: object) -> bool:
    return True


def download(id: str, options: DownloadOptions) -> Stream[bytes, ChatError]:
    """Streams the file behind an attachment id.

    Every hop must pass ``safe_url``. The first must have a host in the id's
    own allowlist (exact ``connector_hosts`` for ``connector:``,
    ``file_host_suffixes`` for ``preauth:``), and a redirect a host there or
    in ``redirect_hosts``. A redirect host never receives the token. The
    first hop of a ``connector:`` id must also have the ``CONNECTOR_PATH``
    shape. A URL that fails fails ``Forbidden`` with detail
    ``untrusted_url``.

    Requests carry only the bearer token, on the first hop of a
    ``connector:`` id. Redirects are read by hand, at most ``MAX_REDIRECTS``
    of them, and only 301, 302, 303, 307 and 308, each sent again as a GET;
    the client follows none itself, and a response from another URL than
    the request's is refused. Errors and spans hold the host only: a
    ``preauth:`` URL is a credential, so the client's own span is off."""
    too_large = _errors.chat_error(_OP, _errors.too_large("files", "max_bytes"))

    @fx.gen
    def make() -> Generator[Effect[Any, ChatError, Any], Any, Stream[bytes, ChatError]]:  # noqa: PLR0911
        parsed = parse_id(id)
        if parsed is None:
            return (yield from _fail(_errors.invalid_request("attachment_id")))
        kind, raw = parsed
        if kind == "url":
            return (yield from _fail(_errors.unsupported("download", "url_attachment")))

        # The id's own allowlist. ``redirect_hosts`` never vouches for the
        # first hop, since the first hop of a ``connector:`` id has the token.
        def own(url: Url) -> bool:
            if kind == "connector":
                return url.hostname in options.connector_hosts
            return under_suffix(url.hostname, options.file_host_suffixes)

        first = safe_url(raw)
        if (
            first is None
            or not own(first)
            or (
                kind == "connector"
                and (first.search or CONNECTOR_PATH.fullmatch(first.pathname) is None)
            )
        ):
            return (yield from _fail(_errors.untrusted_url()))

        http = options.http.with_scope()

        def send(url: Url, hop: int) -> Effect[HttpClientResponse, ChatError, Any]:
            @fx.gen
            def run() -> Generator[Effect[Any, ChatError, Any], Any, HttpClientResponse]:
                request = http_request.get(url.href)
                if kind == "connector" and hop == 0:
                    token = yield from options.token.map_error(
                        lambda error: _errors.with_op(_OP, error)
                    )
                    request = request.bearer_token(token)
                response: HttpClientResponse = yield from (
                    http.execute(request)
                    .pipe(fx.provide_service(FollowRedirects, False))
                    .pipe(fx.provide_service(TracerDisabledWhen, _no_trace))
                    .map_error(
                        lambda error: _errors.chat_error(
                            _OP, _errors.transport(False, type(error.reason).__name__)
                        )
                    )
                )
                yield from annotate_current_span("http.response.status_code", response.status)
                if response.url != url.href:
                    return (yield from _fail(_errors.untrusted_url()))
                return response

            return run.with_span(
                "TeamsChat.download.request",
                kind="client",
                attributes={"server.address": url.hostname, "teams.download.hop": hop},
            )

        url = first
        hop = 0
        while True:
            response = yield from send(url, hop)
            if response.status not in _REDIRECTS:
                break
            if hop == MAX_REDIRECTS:
                return (yield from _fail(_errors.invalid_response(False, "too_many_redirects")))
            location = response.headers.get("location")
            if location is None:
                return (yield from _fail(_errors.invalid_response(False, "missing_location")))
            following = safe_url(location, url.href)
            if following is None or not (
                own(following) or following.hostname in options.redirect_hosts
            ):
                return (yield from _fail(_errors.untrusted_url()))
            url = following
            hop += 1

        if not 200 <= response.status < 300:
            return (yield from _fail(_errors.reason_for_status(response.status, write=False)))
        length = _content_length(response.headers.get("content-length"))
        if length is not None and length > options.max_bytes:
            return (yield from fx.fail(too_large))
        received = 0

        def counted(chunk: bytes) -> Effect[bytes, ChatError]:
            nonlocal received
            received += len(chunk)
            return fx.fail(too_large) if received > options.max_bytes else fx.succeed(chunk)

        return response.stream.map_error(
            lambda error: _errors.chat_error(
                _OP, _errors.transport(False, type(error.reason).__name__)
            )
        ).map_effect(counted)

    return _stream.unwrap(make)


_DIGITS = re.compile(r"[0-9]{1,20}")


def _content_length(value: str | None) -> int | None:
    """A ``Content-Length`` header as a number, when it is whole ASCII digits."""
    if value is None:
        return None
    text = value.strip()
    return int(text) if _DIGITS.fullmatch(text) else None
