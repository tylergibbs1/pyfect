"""Checking archive entries that came from someone else."""

from pathlib import PureWindowsPath

import pyfect as fx
from pyfect import stream
from pyfect.encoding import tar

MAX_BODY_SIZE = 1024 * 1024


def is_safe(header: tar.Header) -> bool:
    """A relative path that stays inside the target directory, and no links, which
    could redirect a later entry out of it. ``PureWindowsPath`` reads both separators
    and drive letters, whichever system the entries end up on."""
    path = PureWindowsPath(header.path)
    return (
        header.type in ("File", "Directory")
        and not path.anchor
        and ".." not in path.parts
        and header.size <= MAX_BODY_SIZE
    )


entries: list[tar.Entry] = [
    tar.file("notes.txt", "fine"),
    tar.file("../../etc/passwd", "not fine"),
    tar.symlink("link", "/etc"),
]
untrusted = fx.run_sync(
    stream.from_iterable(entries).pipe_through_channel(tar.encode()).run_bytes().or_die()
)

decoded = stream.make(untrusted).pipe_through_channel(tar.decode())
checked = decoded.map(lambda entry: (entry.header.path, is_safe(entry.header)))
print(fx.run_sync(checked.run_collect().or_die()))
