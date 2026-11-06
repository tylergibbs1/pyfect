"""Node's ``path.posix`` algorithms, as Effect's ``Path`` has them."""

from __future__ import annotations

import os


def _segments(path: str, *, above_root: bool) -> str:
    out: list[str] = []
    for segment in path.split("/"):
        if segment in {"", "."}:
            continue
        if segment != "..":
            out.append(segment)
        elif out and out[-1] != "..":
            out.pop()
        elif above_root:
            out.append("..")
    return "/".join(out)


def normalize(path: str) -> str:
    if not path:
        return "."
    absolute = path[0] == "/"
    trailing = path[-1] == "/"
    body = _segments(path, above_root=not absolute)
    if not body:
        return "/" if absolute else ("./" if trailing else ".")
    if trailing:
        body += "/"
    return "/" + body if absolute else body


def join(*paths: str) -> str:
    parts = [part for part in paths if part]
    return normalize("/".join(parts)) if parts else "."


def resolve(*segments: str) -> str:
    resolved = ""
    for segment in reversed(segments):
        if segment:
            resolved = f"{segment}/{resolved}"
            if segment[0] == "/":
                break
    else:
        resolved = f"{os.getcwd()}/{resolved}"
    return "/" + _segments(resolved, above_root=False)


def relative(from_: str, to: str) -> str:
    start = [part for part in resolve(from_).split("/") if part]
    end = [part for part in resolve(to).split("/") if part]
    common = 0
    while common < min(len(start), len(end)) and start[common] == end[common]:
        common += 1
    return "/".join([*[".."] * (len(start) - common), *end[common:]])


def _last_segment(path: str) -> str:
    return path.rstrip("/").rpartition("/")[2]


def basename(path: str, suffix: str = "") -> str:
    if suffix and path == suffix:
        return ""
    base = _last_segment(path)
    if suffix and base != suffix and base.endswith(suffix):
        return base[: -len(suffix)]
    return base


def dirname(path: str) -> str:
    if not path:
        return "."
    rooted = path[0] == "/"
    stripped = path.rstrip("/")
    end = stripped.rfind("/", 1)
    if end == -1:
        return "/" if rooted else "."
    if rooted and end == 1:
        return "//"
    return stripped[:end]


def extname(path: str) -> str:
    base = _last_segment(path)
    dot = base.rfind(".")
    return "" if dot <= 0 or base == ".." else base[dot:]


def directory_of_parse(path: str) -> str:
    """``path.parse``'s ``dir``: ``dirname``, but a relative path with one
    segment has none."""
    stripped = path.rstrip("/")
    end = stripped.rfind("/")
    if end > 0:
        return stripped[:end]
    return "/" if path.startswith("/") else ""
