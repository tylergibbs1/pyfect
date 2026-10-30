"""HTTP server responses (Effect's ``HttpServerResponse``).

A response is an immutable value: status, headers, cookies and a body (an
``HttpBody``). Build one with ``text``, ``json``, ``stream``, ``empty``,
``redirect``... and refine it with its methods, each giving a new
response::

    response.text("created", status=201).set_header("x-request-id", rid)

A body with a content type or length sets ``content-type`` /
``content-length`` when the response is made (an explicit header given with
``set_header`` wins over the body's).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import TYPE_CHECKING, ClassVar, Never, TypedDict, Unpack, cast, final

from pyfect._core import Effect
from pyfect._digits import parse_digits
from pyfect.cause import UnhandledError
from pyfect.effect import die, from_async, from_result, succeed
from pyfect.http import _form_data
from pyfect.http import body as _body
from pyfect.http import template as _template
from pyfect.http import url_params as _url_params
from pyfect.http.cookies import EMPTY as EMPTY_COOKIES
from pyfect.http.cookies import CookieOptionsInput, Cookies, CookiesError
from pyfect.http.error import EmptyBodyError, HttpClientError
from pyfect.http.headers import EMPTY as EMPTY_HEADERS
from pyfect.http.headers import Headers
from pyfect.http.headers import Input as HeadersInput
from pyfect.http.headers import from_input as headers_from_input
from pyfect.http.request import HttpClientRequest
from pyfect.http.request import get as get_request
from pyfect.http.response import HttpClientResponse
from pyfect.http.web import WebResponse
from pyfect.schema import Codec
from pyfect.schema._options import ParseOptions
from pyfect.stream import Stream, from_effect
from pyfect.stream import empty as empty_stream

if TYPE_CHECKING:
    from pyfect.http.file_like import FileLike
    from pyfect.http.platform import FileOptions, FileWebOptions, HttpPlatform
    from pyfect.platform_error import PlatformError


class Options(TypedDict, total=False):
    """What a response is made with, besides its body."""

    status: int
    status_text: str
    headers: HeadersInput
    cookies: Cookies


class ContentTypeOptions(Options, total=False):
    content_type: str


class RawOptions(ContentTypeOptions, total=False):
    content_length: int


type CookieEntry = tuple[str, str] | tuple[str, str, CookieOptionsInput]


@final
class HttpServerResponse:
    """A response. Error reporters skip it when it is a failure
    (``report_ignored``)."""

    __slots__ = ("body", "cookies", "headers", "status", "status_text")

    report_ignored: ClassVar[bool] = True

    status: int
    status_text: str | None
    headers: Headers
    cookies: Cookies
    body: _body.HttpBody

    def __init__(
        self,
        status: int,
        status_text: str | None = None,
        headers: Headers | None = None,
        cookies: Cookies | None = None,
        body: _body.HttpBody | None = None,
        *,
        owned_headers: Headers | None = None,
    ) -> None:
        """A response whose content headers follow ``body``; with
        ``owned_headers`` (replacing ``headers``), headers already set there
        win over the body's."""
        self.status = status
        self.status_text = status_text
        self.cookies = EMPTY_COOKIES if cookies is None else cookies
        self.body = _body.EMPTY if body is None else body
        content_type = self.body.content_type
        content_length = self.body.content_length
        base = owned_headers if owned_headers is not None else headers or EMPTY_HEADERS
        if content_type or content_length is not None:
            owned = owned_headers is not None
            added: dict[str, str] = {}
            if content_type and (not owned or "content-type" not in base):
                added["content-type"] = content_type
            if content_length is not None and (not owned or "content-length" not in base):
                added["content-length"] = str(content_length)
            self.headers = base.set_all(added) if added else base
        else:
            self.headers = base

    def __repr__(self) -> str:
        return f"HttpServerResponse({self.status}, body={self.body.tag})"

    def __http_response__(self) -> Effect[HttpServerResponse]:
        return succeed(self)

    def to_json(self) -> dict[str, object]:
        return {
            "_id": "HttpServerResponse",
            "status": self.status,
            "status_text": self.status_text,
            "headers": self.headers.to_json(),
            "cookies": self.cookies.to_json(),
            "body": self.body.to_json(),
        }

    def _replace(
        self,
        *,
        status: int | None = None,
        status_text: str | None = None,
        headers: Headers | None = None,
        cookies: Cookies | None = None,
    ) -> HttpServerResponse:
        return HttpServerResponse(
            self.status if status is None else status,
            self.status_text if status_text is None else status_text,
            self.headers if headers is None else headers,
            self.cookies if cookies is None else cookies,
            self.body,
        )

    def set_header(self, key: str, value: str) -> HttpServerResponse:
        return HttpServerResponse(
            self.status,
            self.status_text,
            cookies=self.cookies,
            body=self.body,
            owned_headers=self.headers.set(key, value),
        )

    def set_headers(self, headers: HeadersInput) -> HttpServerResponse:
        return HttpServerResponse(
            self.status,
            self.status_text,
            cookies=self.cookies,
            body=self.body,
            owned_headers=self.headers.set_all(headers),
        )

    def remove_header(self, key: str) -> HttpServerResponse:
        return self._replace(headers=self.headers.remove(key))

    def set_status(self, status: int, status_text: str | None = None) -> HttpServerResponse:
        return self._replace(status=status, status_text=status_text)

    def set_body(self, body: _body.HttpBody) -> HttpServerResponse:
        """The response with ``body``, its content headers following it."""
        return HttpServerResponse(
            self.status,
            self.status_text,
            cookies=self.cookies,
            body=body,
            owned_headers=_body.update_headers(self.headers, body),
        )

    def set_body_keep_headers(self, body: _body.HttpBody) -> HttpServerResponse:
        """The response with ``body`` and its headers unchanged."""
        response = object.__new__(HttpServerResponse)
        response.status = self.status
        response.status_text = self.status_text
        response.headers = self.headers
        response.cookies = self.cookies
        response.body = body
        return response

    def remove_cookie(self, name: str) -> HttpServerResponse:
        return self._replace(cookies=self.cookies.remove(name))

    def replace_cookies(self, cookies: Cookies) -> HttpServerResponse:
        return self._replace(cookies=cookies)

    def merge_cookies(self, cookies: Cookies) -> HttpServerResponse:
        return self._replace(cookies=self.cookies.merge(cookies))

    def update_cookies(self, f: Callable[[Cookies], Cookies]) -> HttpServerResponse:
        return self._replace(cookies=f(self.cookies))

    def set_cookie(
        self, name: str, value: str, **options: Unpack[CookieOptionsInput]
    ) -> Effect[HttpServerResponse, CookiesError]:
        return from_result(self.cookies.set(name, value, **options)).map(
            lambda cookies: self._replace(cookies=cookies)
        )

    def set_cookie_unsafe(
        self, name: str, value: str, **options: Unpack[CookieOptionsInput]
    ) -> HttpServerResponse:
        return self._replace(cookies=self.cookies.set_unsafe(name, value, **options))

    def expire_cookie(
        self, name: str, **options: Unpack[CookieOptionsInput]
    ) -> Effect[HttpServerResponse, CookiesError]:
        return from_result(self.cookies.expire_cookie(name, **options)).map(
            lambda cookies: self._replace(cookies=cookies)
        )

    def expire_cookie_unsafe(
        self, name: str, **options: Unpack[CookieOptionsInput]
    ) -> HttpServerResponse:
        return self._replace(cookies=self.cookies.expire_cookie_unsafe(name, **options))

    def set_cookies(
        self, cookies: Iterable[CookieEntry]
    ) -> Effect[HttpServerResponse, CookiesError]:
        return from_result(self.cookies.set_all(cookies)).map(
            lambda cookies: self._replace(cookies=cookies)
        )

    def set_cookies_unsafe(self, cookies: Iterable[CookieEntry]) -> HttpServerResponse:
        return self._replace(cookies=self.cookies.set_all_unsafe(cookies))


def is_http_server_response(value: object) -> bool:
    return isinstance(value, HttpServerResponse)


def _headers(options: Options) -> Headers:
    given = options.get("headers")
    return EMPTY_HEADERS if given is None else headers_from_input(given)


def _content_type(options: ContentTypeOptions, headers: Headers) -> str | None:
    content_type = options.get("content_type")
    if content_type:
        return content_type
    if options.get("headers") is not None:
        return headers.get("content-type")
    return None


def _make(
    options: Options, default_status: int, headers: Headers, body: _body.HttpBody | None
) -> HttpServerResponse:
    return HttpServerResponse(
        options.get("status", default_status),
        options.get("status_text"),
        headers,
        options.get("cookies"),
        body,
    )


def empty(**options: Unpack[Options]) -> HttpServerResponse:
    """No body; ``204`` unless ``status`` says otherwise."""
    return _make(options, 204, _headers(options), None)


def redirect(location: str, **options: Unpack[Options]) -> HttpServerResponse:
    """A ``location`` redirect; ``302`` unless ``status`` says otherwise."""
    headers = Headers({"location": location})
    given = options.get("headers")
    if given is not None:
        headers = headers.merge(headers_from_input(given))
    return _make(options, 302, headers, None)


def bytes_(body: bytes, **options: Unpack[ContentTypeOptions]) -> HttpServerResponse:
    """Bytes, ``application/octet-stream`` by default (Effect's
    ``uint8Array``)."""
    headers = _headers(options)
    return _make(options, 200, headers, _body.bytes_(body, _content_type(options, headers)))


def text(body: str, **options: Unpack[ContentTypeOptions]) -> HttpServerResponse:
    """UTF-8 text, ``text/plain`` by default."""
    headers = _headers(options)
    return _make(options, 200, headers, _body.text(body, _content_type(options, headers)))


def html(body: str, **options: Unpack[Options]) -> HttpServerResponse:
    """``body`` as ``text/html``."""
    return text(body, **options, content_type="text/html")


def html_template[EE = Never, RR = Never](
    strings: Sequence[str], *args: _template.Interpolated[EE, RR]
) -> Effect[HttpServerResponse, EE, RR]:
    """The template's text as ``text/html`` (Effect's tagged ``html``)."""
    return _template.make(strings, *args).map(html)


def html_stream[EE = Never, RR = Never](
    strings: Sequence[str], *args: _template.InterpolatedWithStream[EE, RR]
) -> HttpServerResponse:
    """The template streamed as ``text/html``, each part as it is known."""
    chunks = _template.stream(strings, *args).encode_text()
    return stream(cast("Stream[bytes, object]", chunks), content_type="text/html")


def json(
    body: object, **options: Unpack[ContentTypeOptions]
) -> Effect[HttpServerResponse, _body.HttpBodyError]:
    """``body`` as JSON, failing when it has no JSON form."""
    headers = _headers(options)
    return _body.json(body, _content_type(options, headers)).map(
        lambda encoded: _make(options, 200, headers, encoded)
    )


def json_unsafe(body: object, **options: Unpack[ContentTypeOptions]) -> HttpServerResponse:
    """``body`` as JSON; raises when it has no JSON form."""
    headers = _headers(options)
    return _make(options, 200, headers, _body.json_unsafe(body, _content_type(options, headers)))


class JsonResponder[T, RE]:
    """What ``schema_json`` gives: call it with a value (and response
    options) for its JSON response."""

    __slots__ = ("_encode",)

    def __init__(self, schema: Codec[T, object, object, RE], options: ParseOptions) -> None:
        self._encode = _body.json_schema(schema, **options)

    def __call__(
        self, body: T, **options: Unpack[ContentTypeOptions]
    ) -> Effect[HttpServerResponse, _body.HttpBodyError, RE]:
        headers = _headers(options)
        return self._encode(body, _content_type(options, headers)).map(
            lambda encoded: _make(options, 200, headers, encoded)
        )


def file(
    path: str, **options: Unpack[FileOptions]
) -> Effect[HttpServerResponse, PlatformError, HttpPlatform]:
    """The file at ``path``, streamed by the ``HttpPlatform``."""
    from pyfect.http.platform import HttpPlatform

    return HttpPlatform().flat_map(lambda platform: platform.file_response(path, **options))


def file_web(
    file: FileLike, **options: Unpack[FileWebOptions]
) -> Effect[HttpServerResponse, Never, HttpPlatform]:
    """A file-like value, streamed by the ``HttpPlatform``."""
    from pyfect.http.platform import HttpPlatform

    return HttpPlatform().flat_map(lambda platform: platform.file_web_response(file, **options))


def schema_json[T, RE](
    schema: Codec[T, object, object, RE], **options: Unpack[ParseOptions]
) -> JsonResponder[T, RE]:
    """JSON responses of ``schema``'s values, encoded by the schema."""
    return JsonResponder(schema, options)


def url_params(
    body: _url_params.Input, **options: Unpack[ContentTypeOptions]
) -> HttpServerResponse:
    """The parameters form-encoded, ``application/x-www-form-urlencoded``
    by default."""
    headers = _headers(options)
    content_type = _content_type(options, headers) or "application/x-www-form-urlencoded"
    return _make(options, 200, headers, _body.text(_url_params.to_string(body), content_type))


def raw(body: object, **options: Unpack[RawOptions]) -> HttpServerResponse:
    """A body the server writes as it is (bytes, ``str``)."""
    return HttpServerResponse(
        options.get("status", 200),
        options.get("status_text"),
        None if options.get("headers") is None else _headers(options),
        options.get("cookies"),
        _body.raw(
            body,
            content_type=options.get("content_type"),
            content_length=options.get("content_length"),
        ),
    )


def form_data(body: _body.FormData, **options: Unpack[Options]) -> HttpServerResponse:
    """A multipart form; the server writes its content type."""
    return HttpServerResponse(
        options.get("status", 200),
        options.get("status_text"),
        None if options.get("headers") is None else _headers(options),
        options.get("cookies"),
        body,
    )


def stream(body: Stream[bytes, object], **options: Unpack[RawOptions]) -> HttpServerResponse:
    """A body written as it is pulled."""
    headers = _headers(options)
    return _make(
        options,
        200,
        headers,
        _body.stream(body, _content_type(options, headers), options.get("content_length")),
    )


def omits_body(response: HttpServerResponse, without_body: bool = False) -> bool:
    """Whether the response is sent without its body (``without_body``, as
    for ``HEAD``, or a 204, 205 or 304 status)."""
    return without_body or response.status in (204, 205, 304)


def omits_content_length(status: int) -> bool:
    """204 and 205 responses drop ``content-length``; HEAD and 304 keep the
    representation's."""
    return status in (204, 205)


class _ServerClientResponse(HttpClientResponse):
    """A server response read as a client response (Effect's
    ``toClientResponse``)."""

    def __init__(self, request: HttpClientRequest, response: HttpServerResponse) -> None:
        body = response.body
        headers = response.headers
        content: bytes | Stream[bytes, object]
        match body:
            case _body.Empty():
                content = b""
            case _body.Bytes():
                content = body.body
            case _body.Stream():
                content = body.stream
            case _body.FormData():
                content, content_type = _form_data.encode(body)
                headers = headers.set("content-type", content_type)
            case _body.Raw():
                content = _raw_content(body.body)
        super().__init__(
            request,
            response.status,
            headers,
            content,
            url="" if request is _EMPTY_REQUEST else None,
            set_cookie=response.cookies.to_set_cookie_headers(),
        )
        self.server_response = response

    def to_json(self) -> dict[str, object]:
        return {
            "_id": "HttpClientResponse",
            "request": self.request.to_json(),
            "status": self.status,
            "headers": self.headers.to_json(),
        }


def _raw_content(value: object) -> bytes | Stream[bytes, object]:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode()
    if isinstance(value, WebResponse):
        web = value
        if web.body is None or isinstance(web.body, bytes):
            return web.body or b""
        # Buffered, so the response can still be served afterwards.
        return from_effect(from_async(web.buffer))
    raise TypeError(f"a raw body of type {type(value).__name__} has no bytes")


_EMPTY_REQUEST = get_request("")


def to_client_response(
    response: HttpServerResponse, *, request: HttpClientRequest | None = None
) -> HttpClientResponse:
    """``response`` as an ``HttpClientResponse`` to ``request`` (by default
    an empty one, whose response URL is ``""``)."""
    return _ServerClientResponse(_EMPTY_REQUEST if request is None else request, response)


def _is_empty_body_error(error: HttpClientError) -> bool:
    return isinstance(error.reason, EmptyBodyError)


def parse_content_length(value: str | None) -> int | None:
    """A ``content-length`` value of digits only, as an exact JavaScript
    number; anything else is unknown."""
    parsed = None if value is None else parse_digits(value)
    return parsed if parsed is not None and parsed <= 2**53 - 1 else None


def from_client_response(response: HttpClientResponse) -> HttpServerResponse:
    """A server response streaming ``response``'s body, with its status,
    headers and cookies (no body becomes an empty stream)."""
    headers = response.headers.remove("set-cookie")
    chunks = response.stream.catch_if(_is_empty_body_error, lambda _: empty_stream)
    return HttpServerResponse(
        response.status,
        headers=headers,
        cookies=response.cookies,
        body=_body.stream(
            cast("Stream[bytes, object]", chunks),
            headers.get("content-type"),
            parse_content_length(headers.get("content-length")),
        ),
    )


def die_with(response: HttpServerResponse) -> Effect[Never]:
    """Die with ``response`` as the defect; servers send it as is (Effect's
    ``Effect.die(response)``)."""
    return die(UnhandledError(response))


def response_of_defect(defect: BaseException) -> HttpServerResponse | None:
    """The response a defect carries (``die_with`` / ``or_die`` wrap it in
    an ``UnhandledError``)."""
    if isinstance(defect, UnhandledError) and isinstance(defect.error, HttpServerResponse):
        return defect.error
    return None


__all__ = [
    "ContentTypeOptions",
    "CookieEntry",
    "HttpServerResponse",
    "JsonResponder",
    "Options",
    "RawOptions",
    "bytes_",
    "die_with",
    "empty",
    "file",
    "file_web",
    "form_data",
    "from_client_response",
    "html",
    "html_stream",
    "html_template",
    "is_http_server_response",
    "json",
    "json_unsafe",
    "omits_body",
    "omits_content_length",
    "parse_content_length",
    "raw",
    "redirect",
    "response_of_defect",
    "schema_json",
    "stream",
    "text",
    "to_client_response",
    "url_params",
]
