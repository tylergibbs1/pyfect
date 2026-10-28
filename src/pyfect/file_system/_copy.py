"""``copy``: Node's recursive ``fs.cp``, which Effect's Node file system
calls. Symbolic links are copied as links (a relative target made absolute),
missing parents of the destination are made, and a destination that is the
source, lies inside it, or is a directory where the source is a file (or the
reverse) is refused before anything is written."""

from __future__ import annotations

import errno
import os
import shutil
import stat


def _refuse(message: str, source: str, target: str) -> OSError:
    # Node's ERR_FS_CP_* codes, which Effect tags Unknown, as EINVAL does.
    return OSError(errno.EINVAL, f"cp: {message}", source, None, target)


def _lstat(path: str) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None


def _inside(source: str, target: str) -> bool:
    parts = [p for p in os.path.abspath(source).split(os.sep) if p]
    under = [p for p in os.path.abspath(target).split(os.sep) if p]
    return under[: len(parts)] == parts


def _check(source: str, target: str) -> tuple[os.stat_result, os.stat_result | None]:
    """Node's ``checkPaths``: the source's and destination's ``lstat``."""
    info = os.lstat(source)
    existing = _lstat(target)
    is_dir = stat.S_ISDIR(info.st_mode)
    if existing is not None:
        if (existing.st_dev, existing.st_ino) == (info.st_dev, info.st_ino):
            raise _refuse("src and dest cannot be the same", source, target)
        if is_dir and not stat.S_ISDIR(existing.st_mode):
            raise _refuse("cannot overwrite non-directory with directory", source, target)
        if not is_dir and stat.S_ISDIR(existing.st_mode):
            raise _refuse("cannot overwrite directory with non-directory", source, target)
    if is_dir and _inside(source, target):
        raise _refuse("cannot copy to a subdirectory of self", source, target)
    return info, existing


def _copy_link(source: str, target: str, existing: os.stat_result | None) -> None:
    link = os.readlink(source)
    if not os.path.isabs(link):
        link = os.path.abspath(os.path.join(os.path.dirname(source), link))
    if existing is not None and stat.S_ISLNK(existing.st_mode):
        os.unlink(target)
    os.symlink(link, target)


def _copy_one(
    source: str,
    target: str,
    info: os.stat_result,
    existing: os.stat_result | None,
    *,
    overwrite: bool,
    preserve_timestamps: bool,
) -> None:
    mode = info.st_mode
    if stat.S_ISDIR(mode):
        if existing is None:
            os.mkdir(target)
        for name in os.listdir(source):
            child, child_target = os.path.join(source, name), os.path.join(target, name)
            child_info, child_existing = _check(child, child_target)
            _copy_one(
                child,
                child_target,
                child_info,
                child_existing,
                overwrite=overwrite,
                preserve_timestamps=preserve_timestamps,
            )
        if existing is None:
            os.chmod(target, stat.S_IMODE(mode))
    elif stat.S_ISLNK(mode):
        _copy_link(source, target, existing)
    elif stat.S_ISREG(mode):
        if existing is not None:
            if not overwrite:
                return
            os.unlink(target)
        shutil.copyfile(source, target)
        os.chmod(target, stat.S_IMODE(mode))
        if preserve_timestamps:
            os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns))
    else:
        raise _refuse("cannot copy a special file", source, target)


def copy_tree(source: str, target: str, overwrite: bool, preserve_timestamps: bool) -> None:
    """Node's ``fs.cp(source, target, {recursive: true, force: overwrite,
    preserveTimestamps})``. Without ``overwrite``, files that exist at the
    destination are kept."""
    info, existing = _check(source, target)
    # Node's dirname ignores a trailing separator.
    parent = os.path.dirname(target.rstrip(os.sep + (os.altsep or "")))
    if parent:
        os.makedirs(parent, exist_ok=True)
    _copy_one(
        source,
        target,
        info,
        existing,
        overwrite=overwrite,
        preserve_timestamps=preserve_timestamps,
    )
