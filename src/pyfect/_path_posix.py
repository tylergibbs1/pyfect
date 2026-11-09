"""Node's ``path.posix`` algorithms, as Effect's ``Path`` has them."""

from __future__ import annotations

import os

sep = "/"
delimiter = ":"


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
    absolute = False
    for segment in reversed(segments):
        if segment:
            resolved = f"{segment}/{resolved}"
            absolute = segment[0] == "/"
            if absolute:
                break
    if not absolute:
        # Node keeps a relative result when the working directory isn't absolute.
        cwd = os.getcwd()
        resolved = f"{cwd}/{resolved}"
        absolute = cwd.startswith("/")
    body = _segments(resolved, above_root=not absolute)
    return "/" + body if absolute else body or "."


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


def parse(path: str) -> tuple[str, str, str, str, str]:
    """Node's ``path.posix.parse``: root, dir, base, ext and name. Its own scan, as its check
    for a last segment of ``..`` misses one right below the root (``/..`` has the ext ``.``)."""
    if not path:
        return "", "", "", "", ""
    absolute = path.startswith("/")
    first = 1 if absolute else 0
    start_dot = end = -1
    start_part = 0
    before_dot = 0  # 0: nothing seen before the dot, 1: more dots, -1: another character
    for i in range(len(path) - 1, first - 1, -1):
        char = path[i]
        if char == "/":
            if end != -1:
                start_part = i + 1
                break
            continue
        if end == -1:
            end = i + 1
        if char == ".":
            if start_dot == -1:
                start_dot = i
            elif before_dot != 1:
                before_dot = 1
        elif start_dot != -1:
            before_dot = -1
    base = ext = name = ""
    if end != -1:
        begin = 1 if start_part == 0 and absolute else start_part
        base = path[begin:end]
        is_dots = before_dot == 1 and start_dot == end - 1 and start_dot == start_part + 1
        if start_dot == -1 or before_dot == 0 or is_dots:
            name = base
        else:
            name, ext = path[begin:start_dot], path[start_dot:end]
    directory = path[: start_part - 1] if start_part > 0 else "/" if absolute else ""
    return "/" if absolute else "", directory, base, ext, name


def is_absolute(path: str) -> bool:
    return path.startswith("/")


def to_namespaced_path(path: str) -> str:
    return path
