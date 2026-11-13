"""Following redirects (Effect's ``HttpClient.followRedirects``)."""

from __future__ import annotations

from typing import Any

from pyfect.effect import Effect, succeed, suspend, sync
from pyfect.http import body as _body
from pyfect.http import url as _url
from pyfect.http import url_params as _url_params
from pyfect.http.client._service import HttpClientService
from pyfect.http.headers import Headers, current_redacted_names, is_redacted_name
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.result import Ok

_CREDENTIALS = ("authorization", "proxy-authorization", "cookie")
# Representation headers of the dropped body (RFC 9110 section 15.4).
_CONTENT_HEADERS = ("content-encoding", "content-language", "content-location")


def _without_credentials(headers: Headers) -> Headers:
    """``headers`` for another origin: without the credential headers and
    without any header ``CurrentRedactedNames`` marks as secret (an API
    key such as ``x-api-key``). Effect drops only ``authorization`` and
    ``proxy-authorization``."""
    secret = current_redacted_names()
    drop = [name for name in headers if is_redacted_name(name, secret)]
    return headers.remove_many((*_CREDENTIALS, *drop))


def _next_request(
    response: HttpClientResponse, request: HttpClientRequest
) -> HttpClientRequest | None:
    """The request following ``response``, or ``None`` when its
    ``Location`` is not a URL or leaves ``https`` for ``http`` (Effect
    follows a downgrade; its body and URL would travel in plain text)."""
    location = response.headers["location"]
    match _url.from_string(location, response.request.url):
        case Ok(url):
            pass
        case _:
            return None
    previous = _url.parse(response.request.url)
    if previous.protocol == "https:" and url.protocol != "https:":
        return None
    status = response.status
    if ((status in (301, 302)) and request.method == "POST") or (
        status == 303 and request.method not in ("GET", "HEAD")
    ):
        request = (
            request.set_method("GET")
            .set_body(_body.EMPTY)
            .update_headers(lambda headers: headers.remove_many(_CONTENT_HEADERS))
        )
    if _url.origin(url) != _url.origin(previous):
        request = request.update_headers(_without_credentials)
    return HttpClientRequest(
        request.method,
        _url.set_hash(url, "").href,
        _url_params.EMPTY,
        url.hash[1:] or None,
        request.headers,
        request.body,
    )


def follow_redirects[E, R](
    client: HttpClientService[E, R], max_redirects: int
) -> HttpClientService[E, R]:
    post = client.postprocess

    def loop(
        requests: Effect[HttpClientRequest, Any, Any], redirects: int
    ) -> Effect[HttpClientResponse, E, R]:
        def run() -> Effect[HttpClientResponse, E, R]:
            current: list[HttpClientRequest] = []

            def remember(request: HttpClientRequest) -> HttpClientRequest:
                current.append(request)
                return request

            def follow(response: HttpClientResponse) -> Effect[HttpClientResponse, E, R]:
                if (
                    not 300 <= response.status < 400
                    or not response.headers.get("location")
                    or redirects >= max_redirects
                ):
                    return succeed(response)
                following = _next_request(response, current[-1] if current else response.request)
                if following is None:
                    return succeed(response)
                # Abort the discarded response to release its connection unread.
                abort = response._abort_unread  # pyright: ignore[reportPrivateUsage]
                return sync(abort).and_then(loop(succeed(following), redirects + 1))

            return post(requests.map(remember)).flat_map(follow)

        return suspend(run)

    return HttpClientService(lambda requests: loop(requests, 0), client.preprocess)
