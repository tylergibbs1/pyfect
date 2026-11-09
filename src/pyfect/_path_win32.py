"""Node's ``path.win32`` algorithms (``lib/path.js``), as Effect's ``Path`` has them under
``NodePath`` on Windows. Pure string rules, the same on any host: ``resolve`` takes the working
directory from ``os.getcwd()`` and a drive's own one from the ``=X:`` environment variable, as
Node does.

Each function follows Node's line by line (its branches and early returns included), so a
change to ``lib/path.js`` can be followed here."""

# ruff: noqa: PLR0911, PLR0912, PLR0915

from __future__ import annotations

import os

sep = "\\"
delimiter = ";"

_RESERVED_NAMES = frozenset(
    (
        *("CON", "PRN", "AUX", "NUL"),
        *(f"COM{n}" for n in range(1, 10)),
        *(f"LPT{n}" for n in range(1, 10)),
        *("COM\xb9", "COM\xb2", "COM\xb3", "LPT\xb9", "LPT\xb2", "LPT\xb3"),
    )
)


def _at(path: str, index: int) -> str:
    """JavaScript's ``charCodeAt``: past either end there is no character."""
    return path[index] if 0 <= index < len(path) else ""


def _is_sep(char: str) -> bool:
    return char in {"/", "\\"}


def _is_drive_letter(char: str) -> bool:
    return char != "" and ("A" <= char <= "Z" or "a" <= char <= "z")


def _has_drive(path: str) -> bool:
    return _is_drive_letter(_at(path, 0)) and _at(path, 1) == ":"


def _is_reserved(path: str, colon: int) -> bool:
    # ``slice(0, -1)`` when there is no colon, as in Node.
    return path[:colon].upper() in _RESERVED_NAMES


def _skip(path: str, index: int, *, separators: bool) -> int:
    while index < len(path) and _is_sep(path[index]) == separators:
        index += 1
    return index


def _unc(path: str) -> tuple[str, int, int] | None:
    """For a path starting with two separators: the server part, where the share starts and
    where it ends, when both are there."""
    j = _skip(path, 2, separators=False)
    if j >= len(path) or j == 2:
        return None
    first = path[2:j]
    last = j
    j = _skip(path, j, separators=True)
    if j >= len(path) or j == last:
        return None
    last = j
    return first, last, _skip(path, j, separators=False)


def _normalize_string(path: str, allow_above_root: bool) -> str:
    """Node's ``normalizeString`` with ``\\`` joining segments."""
    res = ""
    last_segment_length = 0
    last_slash = -1
    dots = 0
    char = ""
    for i in range(len(path) + 1):
        if i < len(path):
            char = path[i]
        elif _is_sep(char):
            break
        else:
            char = "/"
        if _is_sep(char):
            if last_slash == i - 1 or dots == 1:
                pass
            elif dots == 2:
                if len(res) < 2 or last_segment_length != 2 or not res.endswith(".."):
                    if len(res) > 2:
                        last_slash_index = len(res) - last_segment_length - 1
                        if last_slash_index == -1:
                            res = ""
                            last_segment_length = 0
                        else:
                            res = res[:last_slash_index]
                            last_segment_length = len(res) - 1 - res.rfind(sep)
                        last_slash = i
                        dots = 0
                        continue
                    if res:
                        res = ""
                        last_segment_length = 0
                        last_slash = i
                        dots = 0
                        continue
                if allow_above_root:
                    res += f"{sep}.." if res else ".."
                    last_segment_length = 2
            else:
                segment = path[last_slash + 1 : i]
                res = f"{res}{sep}{segment}" if res else segment
                last_segment_length = i - last_slash - 1
            last_slash = i
            dots = 0
        elif char == "." and dots != -1:
            dots += 1
        else:
            dots = -1
    return res


def _cwd_for(device: str) -> str:
    """The working directory ``resolve`` uses for a relative path on ``device``: the drive's
    own (``=X:``), else the process's, else the drive's root when that is on another drive."""
    path = os.environ.get(f"={device}") or os.getcwd()
    if path[:2].lower() != device.lower() and _at(path, 2) == "\\":
        return f"{device}\\"
    return path


def resolve(*args: str) -> str:
    resolved_device = ""
    resolved_tail = ""
    resolved_absolute = False
    for i in range(len(args) - 1, -2, -1):
        if i >= 0:
            path = args[i]
            if not path:
                continue
        elif not resolved_device:
            path = os.getcwd()
            # The working directory itself, its slashes turned (a no-op on Windows).
            if not args or (len(args) == 1 and args[0] in {"", "."} and _is_sep(_at(path, 0))):
                return path.replace("/", "\\")
        else:
            path = _cwd_for(resolved_device)

        root_end = 0
        device = ""
        is_absolute = False
        first = _at(path, 0)
        if len(path) == 1:
            if _is_sep(first):
                root_end = 1
                is_absolute = True
        elif _is_sep(first):
            is_absolute = True
            if _is_sep(_at(path, 1)):
                unc = _unc(path)
                if unc is not None:
                    server, last, j = unc
                    if server not in {".", "?"}:
                        device = f"\\\\{server}\\{path[last:j]}"
                        root_end = j
                    else:
                        device = f"\\\\{server}"
                        root_end = 4
            else:
                root_end = 1
        elif _has_drive(path):
            device = path[:2]
            root_end = 2
            if len(path) > 2 and _is_sep(path[2]):
                is_absolute = True
                root_end = 3

        if device:
            if resolved_device:
                if device.lower() != resolved_device.lower():
                    continue
            else:
                resolved_device = device

        if resolved_absolute:
            if resolved_device:
                break
        else:
            resolved_tail = f"{path[root_end:]}\\{resolved_tail}"
            resolved_absolute = is_absolute
            if is_absolute and resolved_device:
                break

    resolved_tail = _normalize_string(resolved_tail, not resolved_absolute)
    if resolved_absolute:
        return f"{resolved_device}\\{resolved_tail}"
    return f"{resolved_device}{resolved_tail}" or "."


def normalize(path: str) -> str:
    length = len(path)
    if length == 0:
        return "."
    root_end = 0
    device: str | None = None
    is_absolute = False
    first = path[0]
    if length == 1:
        return "\\" if first == "/" else path
    if _is_sep(first):
        is_absolute = True
        if _is_sep(path[1]):
            unc = _unc(path)
            if unc is not None:
                server, last, j = unc
                if server in {".", "?"}:
                    device = f"\\\\{server}"
                    root_end = 4
                    possible = path[4 : path.find(":") + 1]
                    if _is_reserved(possible, len(possible) - 1):
                        device = f"\\\\?\\{possible}"
                        root_end = 4 + len(possible)
                elif j == length:
                    return f"\\\\{server}\\{path[last:]}\\"
                else:
                    device = f"\\\\{server}\\{path[last:j]}"
                    root_end = j
        else:
            root_end = 1
    else:
        colon = path.find(":")
        if colon > 0:
            if _is_drive_letter(first) and colon == 1:
                device = path[:2]
                root_end = 2
                if length > 2 and _is_sep(path[2]):
                    is_absolute = True
                    root_end = 3
            elif _is_reserved(path, colon):
                device = path[: colon + 1]
                root_end = colon + 1

    tail = _normalize_string(path[root_end:], not is_absolute) if root_end < length else ""
    if not tail and not is_absolute:
        tail = "."
    if tail and _is_sep(path[-1]):
        tail += "\\"
    if not is_absolute and device is None and ":" in path:
        # CVE-2024-36139: a relative path must not normalize into one Windows reads as
        # absolute (a drive, or a name ending in a colon).
        if len(tail) >= 2 and _has_drive(tail):
            return f".\\{tail}"
        index = path.find(":")
        while index != -1:
            if index == length - 1 or _is_sep(path[index + 1]):
                return f".\\{tail}"
            index = path.find(":", index + 1)
    if _is_reserved(path, path.find(":")):
        return f".\\{device or ''}{tail}"
    if device is None:
        return f"\\{tail}" if is_absolute else tail
    return f"{device}\\{tail}" if is_absolute else f"{device}{tail}"


def is_absolute(path: str) -> bool:
    if not path:
        return False
    return _is_sep(path[0]) or (len(path) > 2 and _has_drive(path) and _is_sep(path[2]))


def join(*args: str) -> str:
    parts = [arg for arg in args if arg]
    if not parts:
        return "."
    first = parts[0]
    joined = "\\".join(parts)
    # A first part starting with exactly two separators and a name is a UNC path; any other
    # run of leading separators collapses to one, so ``normalize`` doesn't read a UNC root.
    needs_replace = True
    slash_count = 0
    if _is_sep(_at(first, 0)):
        slash_count += 1
        if len(first) > 1 and _is_sep(first[1]):
            slash_count += 1
            if len(first) > 2:
                if _is_sep(first[2]):
                    slash_count += 1
                else:
                    needs_replace = False
    if needs_replace:
        while slash_count < len(joined) and _is_sep(joined[slash_count]):
            slash_count += 1
        if slash_count >= 2:
            joined = f"\\{joined[slash_count:]}"
    # A part naming a device (``COM1:``) is left as written, only its slashes turned.
    for part in joined.split("\\"):
        colon = part.find(":")
        if part and colon != -1 and _is_reserved(part, colon):
            return joined.replace("/", "\\")
    return normalize(joined)


def relative(from_: str, to: str) -> str:
    if from_ == to:
        return ""
    from_orig = resolve(from_)
    to_orig = resolve(to)
    if from_orig == to_orig:
        return ""
    lower_from = from_orig.lower()
    lower_to = to_orig.lower()
    if lower_from == lower_to:
        return ""
    if len(from_orig) != len(lower_from) or len(to_orig) != len(lower_to):
        return _relative_by_segments(from_orig, to_orig)

    from_start = _skip_backslashes(lower_from)
    from_end = _trim_backslashes(lower_from, from_start)
    from_len = from_end - from_start
    to_start = _skip_backslashes(lower_to)
    to_end = _trim_backslashes(lower_to, to_start)
    to_len = to_end - to_start

    length = min(from_len, to_len)
    last_common_sep = -1
    i = 0
    while i < length:
        char = lower_from[from_start + i]
        if char != lower_to[to_start + i]:
            break
        if char == "\\":
            last_common_sep = i
        i += 1

    if i != length:
        if last_common_sep == -1:
            return to_orig
    else:
        if to_len > length:
            if lower_to[to_start + i] == "\\":
                return to_orig[to_start + i + 1 :]
            if i == 2:
                return to_orig[to_start + i :]
        if from_len > length:
            if lower_from[from_start + i] == "\\":
                last_common_sep = i
            elif i == 2:
                last_common_sep = 3
        if last_common_sep == -1:
            last_common_sep = 0

    out = ""
    for j in range(from_start + last_common_sep + 1, from_end + 1):
        if j == from_end or lower_from[j] == "\\":
            out += "\\.." if out else ".."
    to_start += last_common_sep
    if out:
        return f"{out}{to_orig[to_start:to_end]}"
    if _at(to_orig, to_start) == "\\":
        to_start += 1
    return to_orig[to_start:to_end]


def _skip_backslashes(path: str) -> int:
    start = 0
    while start < len(path) and path[start] == "\\":
        start += 1
    return start


def _trim_backslashes(path: str, start: int) -> int:
    """Where ``path`` ends without its trailing backslashes (only a UNC root has them)."""
    end = len(path)
    while end - 1 > start and path[end - 1] == "\\":
        end -= 1
    return end


def _relative_by_segments(from_orig: str, to_orig: str) -> str:
    """Node's ``relative`` when lowercasing changes a path's length (``İ``): segments
    compared one by one, each lowercased."""
    from_split = from_orig.split("\\")
    to_split = to_orig.split("\\")
    if from_split[-1] == "":
        from_split.pop()
    if to_split[-1] == "":
        to_split.pop()
    from_len = len(from_split)
    to_len = len(to_split)
    length = min(from_len, to_len)
    i = 0
    while i < length and from_split[i].lower() == to_split[i].lower():
        i += 1
    if i == 0:
        return to_orig
    if i == length:
        if to_len > length:
            return "\\".join(to_split[i:])
        if from_len > length:
            return "..\\" * (from_len - 1 - i) + ".."
        return ""
    return "..\\" * (from_len - i) + "\\".join(to_split[i:])


def to_namespaced_path(path: str) -> str:
    if not path:
        return path
    resolved = resolve(path)
    if len(resolved) <= 2:
        return path
    if resolved[0] == "\\":
        if resolved[1] == "\\" and resolved[2] not in {"?", "."}:
            return f"\\\\?\\UNC\\{resolved[2:]}"
    elif _has_drive(resolved) and resolved[2] == "\\":
        return f"\\\\?\\{resolved}"
    return resolved


def dirname(path: str) -> str:
    length = len(path)
    if length == 0:
        return "."
    root_end = -1
    offset = 0
    first = path[0]
    if length == 1:
        return path if _is_sep(first) else "."
    if _is_sep(first):
        root_end = offset = 1
        if _is_sep(path[1]):
            unc = _unc(path)
            if unc is not None:
                _server, last, j = unc
                if j == length:
                    return path
                if j != last:
                    root_end = offset = j + 1
    elif _has_drive(path):
        root_end = 3 if length > 2 and _is_sep(path[2]) else 2
        offset = root_end

    end = -1
    matched_slash = True
    for i in range(length - 1, offset - 1, -1):
        if _is_sep(path[i]):
            if not matched_slash:
                end = i
                break
        else:
            matched_slash = False
    if end == -1:
        if root_end == -1:
            return "."
        end = root_end
    return path[:end]


def basename(path: str, suffix: str = "") -> str:
    start = 2 if len(path) >= 2 and _has_drive(path) else 0
    end = -1
    matched_slash = True
    if suffix and len(suffix) <= len(path):
        if suffix == path:
            return ""
        ext_index = len(suffix) - 1
        first_non_slash_end = -1
        for i in range(len(path) - 1, start - 1, -1):
            char = path[i]
            if _is_sep(char):
                if not matched_slash:
                    start = i + 1
                    break
            else:
                if first_non_slash_end == -1:
                    matched_slash = False
                    first_non_slash_end = i + 1
                if ext_index >= 0:
                    if char == suffix[ext_index]:
                        ext_index -= 1
                        if ext_index == -1:
                            end = i
                    else:
                        ext_index = -1
                        end = first_non_slash_end
        if start == end:
            end = first_non_slash_end
        elif end == -1:
            end = len(path)
        return path[start:end]
    for i in range(len(path) - 1, start - 1, -1):
        if _is_sep(path[i]):
            if not matched_slash:
                start = i + 1
                break
        elif end == -1:
            matched_slash = False
            end = i + 1
    return "" if end == -1 else path[start:end]


def _last_part(path: str, root_end: int) -> tuple[int, int, int, int]:
    """Node's scan back from the end over the last part: where it starts and ends, where its
    last dot is, and what came before that dot (0 nothing, 1 more dots, -1 anything else)."""
    start_dot = -1
    start_part = root_end
    end = -1
    matched_slash = True
    pre_dot_state = 0
    for i in range(len(path) - 1, root_end - 1, -1):
        char = path[i]
        if _is_sep(char):
            if not matched_slash:
                start_part = i + 1
                break
            continue
        if end == -1:
            matched_slash = False
            end = i + 1
        if char == ".":
            if start_dot == -1:
                start_dot = i
            elif pre_dot_state != 1:
                pre_dot_state = 1
        elif start_dot != -1:
            pre_dot_state = -1
    return start_part, end, start_dot, pre_dot_state


def _no_extension(start_part: int, end: int, start_dot: int, pre_dot_state: int) -> bool:
    return (
        start_dot == -1
        or pre_dot_state == 0
        # The last part is exactly "..".
        or (pre_dot_state == 1 and start_dot == end - 1 and start_dot == start_part + 1)
    )


def extname(path: str) -> str:
    start = 2 if len(path) >= 2 and _has_drive(path) else 0
    start_part, end, start_dot, pre_dot_state = _last_part(path, start)
    if end == -1 or _no_extension(start_part, end, start_dot, pre_dot_state):
        return ""
    return path[start_dot:end]


def parse(path: str) -> tuple[str, str, str, str, str]:
    """Root, dir, base, ext and name."""
    if not path:
        return "", "", "", "", ""
    length = len(path)
    root_end = 0
    first = path[0]
    if length == 1:
        if _is_sep(first):
            return path, path, "", "", ""
        return "", "", path, "", path
    if _is_sep(first):
        root_end = 1
        if _is_sep(path[1]):
            unc = _unc(path)
            if unc is not None:
                _server, last, j = unc
                if j == length:
                    root_end = j
                elif j != last:
                    root_end = j + 1
    elif _has_drive(path):
        if length <= 2:
            return path, path, "", "", ""
        root_end = 2
        if _is_sep(path[2]):
            if length == 3:
                return path, path, "", "", ""
            root_end = 3
    root = path[:root_end]

    start_part, end, start_dot, pre_dot_state = _last_part(path, root_end)
    base = ext = name = ""
    if end != -1:
        base = path[start_part:end]
        if _no_extension(start_part, end, start_dot, pre_dot_state):
            name = base
        else:
            name = path[start_part:start_dot]
            ext = path[start_dot:end]
    directory = path[: start_part - 1] if 0 < start_part != root_end else root
    return root, directory, base, ext, name
