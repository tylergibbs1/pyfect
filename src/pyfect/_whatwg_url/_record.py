"""The URL record of the URL Standard and its serializations."""

from __future__ import annotations

from dataclasses import dataclass

SPECIAL_PORTS: dict[str, int | None] = {
    "ftp": 21,
    "file": None,
    "http": 80,
    "https": 443,
    "ws": 80,
    "wss": 443,
}

type Path = str | tuple[str, ...]
"""An opaque path (``mailto:x``) is a string; any other a list of segments."""


@dataclass(frozen=True, slots=True)
class UrlRecord:
    """A parsed URL. ``host`` is serialized (``None``: no host; ``""``: the
    empty host); ``query`` and ``fragment`` are ``None`` when absent."""

    scheme: str
    username: str = ""
    password: str = ""
    host: str | None = None
    port: int | None = None
    path: Path = ()
    query: str | None = None
    fragment: str | None = None

    @property
    def special(self) -> bool:
        return self.scheme in SPECIAL_PORTS

    @property
    def has_credentials(self) -> bool:
        return self.username != "" or self.password != ""

    @property
    def cannot_have_credentials_or_port(self) -> bool:
        return self.host is None or self.host == "" or self.scheme == "file"

    @property
    def pathname(self) -> str:
        if isinstance(self.path, str):
            return self.path
        return "".join(f"/{segment}" for segment in self.path)

    def href(self, exclude_fragment: bool = False) -> str:
        out = f"{self.scheme}:"
        if self.host is not None:
            out += "//"
            if self.has_credentials:
                out += self.username + (f":{self.password}" if self.password else "") + "@"
            out += self.host + ("" if self.port is None else f":{self.port}")
        elif not isinstance(self.path, str) and len(self.path) > 1 and self.path[0] == "":
            out += "/."
        out += self.pathname
        if self.query is not None:
            out += f"?{self.query}"
        if not exclude_fragment and self.fragment is not None:
            out += f"#{self.fragment}"
        return out

    def origin(self) -> str:
        """The serialized origin: ``scheme://host[:port]`` for the special
        schemes but ``file`` and for ``blob:`` URLs of ``http(s)`` URLs;
        ``"null"`` otherwise."""
        if self.scheme == "blob":
            from pyfect._whatwg_url._parser import parse

            inner = parse(self.pathname)
            if inner is not None and inner.scheme in ("http", "https"):
                return inner.origin()
            return "null"
        if self.scheme == "file" or not self.special:
            return "null"
        port = "" if self.port is None else f":{self.port}"
        return f"{self.scheme}://{self.host}{port}"
