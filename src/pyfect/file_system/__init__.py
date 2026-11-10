"""Files and directories as a service (Effect's ``FileSystem``).

Programs read the ``FileSystem`` service and get the host's with
``file_system.layer`` (or a test double)::

    from pyfect import file_system
    from pyfect.file_system import FileSystem

    @fx.fn
    def program():
        fs = yield from FileSystem()
        yield from fs.write_file_string("notes.txt", "hello")
        return (yield from fs.read_file_string("notes.txt"))

    fx.run_blocking(program().pipe(fx.provide(file_system.layer)))

Every operation fails with a ``PlatformError`` whose reason is a
``NotFound``, ``PermissionDenied``, ``AlreadyExists``, ``BadResource`` ...
(``fx.platform_error``). ``open`` and the ``*_scoped`` temporaries live
until their scope closes; ``stream`` and ``sink`` read and write files as
byte streams. ``watch`` uses a provided ``WatchBackend``, else the operating
system's change notification with the ``watch`` extra (``WatchfilesBackend``),
else polls (``LiveFileSystem(watch_interval=...)``). ``NoopFileSystem`` / ``layer_noop`` are an
empty file system to subclass in tests.
"""

from pyfect.file_system._file import LiveFile
from pyfect.file_system._live import DEFAULT_WATCH_INTERVAL, LiveFileSystem, layer
from pyfect.file_system._model import (
    Create,
    DirectoryEntry,
    FileInfo,
    FileType,
    OpenFlag,
    Remove,
    SeekMode,
    Update,
    WatchEvent,
)
from pyfect.file_system._native_watch import WatchfilesBackend
from pyfect.file_system._noop import NoopFileSystem, layer_noop
from pyfect.file_system._service import (
    DEFAULT_CHUNK_SIZE,
    File,
    FileSystem,
    FileSystemService,
    WatchBackend,
    WatchBackendService,
)

__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_WATCH_INTERVAL",
    "Create",
    "DirectoryEntry",
    "File",
    "FileInfo",
    "FileSystem",
    "FileSystemService",
    "FileType",
    "LiveFile",
    "LiveFileSystem",
    "NoopFileSystem",
    "OpenFlag",
    "Remove",
    "SeekMode",
    "Update",
    "WatchBackend",
    "WatchBackendService",
    "WatchEvent",
    "WatchfilesBackend",
    "layer",
    "layer_noop",
]
