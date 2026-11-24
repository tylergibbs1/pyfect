"""Port of Effect's ``packages/chat/teams/test/download.test.ts``: a download
sends the bot's token to the Connector only, follows redirects by hand
within the allowlists, and stops past ``max_bytes``."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from _teams_fake import Gen

import pyfect as fx
from pyfect import stream, testing
from pyfect._core import Effect
from pyfect._url import Url
from pyfect.chat.chat_error import AnyReason, ChatError, Forbidden, TooLarge
from pyfect.chat.chat_message import Attachment
from pyfect.chat.teams import _download
from pyfect.http import client
from pyfect.http import response as http_response
from pyfect.http.httpx_client import FollowRedirects
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redacted


@dataclass(frozen=True)
class Sent:
    url: str
    authorization: str | None
    follow_redirects: bool | None


@dataclass(frozen=True)
class Reply:
    status: int = 200
    body: bytes = b""
    headers: dict[str, str] | None = None


def serve(handler: Callable[[str], Reply]) -> tuple[client.HttpClientService[Any], list[Sent]]:
    sent: list[Sent] = []

    def send(request: HttpClientRequest, url: Url, _signal: object, fiber: Any) -> Effect[Any]:
        def answer() -> Any:
            sent.append(
                Sent(url.href, request.headers.get("authorization"), fiber.get_ref(FollowRedirects))
            )
            reply = handler(url.href)
            return http_response.make(
                request, reply.body, status=reply.status, headers=reply.headers or {}, url=url.href
            )

        return fx.sync(answer)

    return client.make(send), sent


CONNECTOR_URL = "https://smba.trafficmanager.net/amer/v3/attachments/0-cus-d1-abc/views/original"


def options(
    http: client.HttpClientService[Any], max_bytes: int = 1024
) -> _download.DownloadOptions:
    return _download.DownloadOptions(
        http=http,
        max_bytes=max_bytes,
        token=fx.succeed(redacted("secret")),
        connector_hosts=frozenset({"smba.trafficmanager.net"}),
        file_host_suffixes=("sharepoint.com",),
        redirect_hosts=frozenset({"cdn.example.com"}),
    )


def reason_of(bytes_: stream.Stream[bytes, ChatError]) -> Effect[AnyReason, Any]:
    return bytes_.run_drain().flip().map(lambda error: error.reason)


@testing.effect
def test_sends_the_token_to_the_connector_and_streams_the_body():
    """download / sends the token to the Connector and streams the body"""
    http, sent = serve(lambda _: Reply(body=b"hello"))

    @fx.gen
    def program() -> Gen[None]:
        chunks = yield from _download.download(
            f"connector:{CONNECTOR_URL}", options(http)
        ).run_collect()
        assert b"".join(chunks) == b"hello"
        assert sent == [Sent(CONNECTOR_URL, "Bearer secret", False)]

    return program


@testing.effect
def test_sends_the_token_on_the_first_hop_only_and_never_to_an_untrusted_url():
    """download / sends the token on the first hop only, and never to an untrusted URL"""

    def redirect(url: str) -> Reply:
        location = (
            "https://cdn.example.com/file" if url == CONNECTOR_URL else "https://evil.example/file"
        )
        return Reply(status=302, headers={"location": location})

    http, sent = serve(redirect)

    @fx.gen
    def program() -> Gen[None]:
        redirected = yield from reason_of(
            _download.download(f"connector:{CONNECTOR_URL}", options(http))
        )
        assert isinstance(redirected, Forbidden)
        assert redirected.detail == "untrusted_url"
        assert [(each.url, each.authorization) for each in sent] == [
            (CONNECTOR_URL, "Bearer secret"),
            ("https://cdn.example.com/file", None),
        ]

        # A redirect host named as the first hop.
        id = "connector:https://cdn.example.com/v3/attachments/a/views/original"
        first = yield from reason_of(_download.download(id, options(http)))
        assert isinstance(first, Forbidden)
        assert first.detail == "untrusted_url"
        assert len(sent) == 2

    return program


@testing.effect
def test_fails_too_large_past_max_bytes():
    """download / fails TooLarge past maxBytes"""
    http, _ = serve(lambda _: Reply(body=bytes(16)))

    @fx.gen
    def program() -> Gen[None]:
        reason = yield from reason_of(
            _download.download(f"connector:{CONNECTOR_URL}", options(http, 8))
        )
        assert isinstance(reason, TooLarge)

    return program


def test_refuses_a_lookalike_file_host():
    """classify / refuses a lookalike file host"""

    def attachment(host: str) -> dict[str, object]:
        return {
            "contentType": _download.FILE_DOWNLOAD_INFO,
            "contentUrl": f"https://{host}/personal/a/report.pdf",
            "name": "report.pdf",
            "content": {"downloadUrl": f"https://{host}/download.aspx?tempauth=x"},
        }

    def classify(host: str) -> Attachment | None:
        return _download.classify(
            attachment(host),
            service_url="https://smba.trafficmanager.net/amer/",
            conversation_type="personal",
            connector_hosts=frozenset({"smba.trafficmanager.net"}),
            file_host_suffixes=("sharepoint.com",),
        )

    assert classify("contoso.sharepoint.com") == Attachment(
        id="preauth:https://contoso.sharepoint.com/download.aspx?tempauth=x", name="report.pdf"
    )
    assert classify("evilsharepoint.com") == Attachment(
        id="url:https://evilsharepoint.com/personal/a/report.pdf", name="report.pdf"
    )
