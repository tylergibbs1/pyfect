"""Writing a zip and a tar archive, and reading them back as they arrive."""

import pyfect as fx
from pyfect import stream
from pyfect.encoding import tar
from pyfect.encoding import zip as zip_archive


def read_zip(entry: zip_archive.Entry[zip_archive.ZipError]):
    return entry.body.run_bytes().map(lambda body: (entry.header.path, body))


def read_tar(entry: tar.Entry[tar.TarError]):
    return entry.body.run_bytes().map(lambda body: (entry.header.path, body))


# In-memory files, and a body streamed while the archive is written
zip_entries: list[zip_archive.Entry | zip_archive.ContentEntry] = [
    zip_archive.directory("logs"),
    zip_archive.file("logs/a.txt", "hello\n"),
    zip_archive.file_stream("logs/b.txt", stream.make(b"str", b"eamed\n")),
]
zipped = fx.run_sync(
    stream.from_iterable(zip_entries)
    .pipe_through_channel(zip_archive.encode())
    .run_bytes()
    .or_die()
)
unzipped = stream.make(zipped).pipe_through_channel(zip_archive.decode()).map_effect(read_zip)
print(fx.run_sync(unzipped.run_collect().or_die()))

tar_entries: list[tar.Entry] = [
    tar.directory("logs"),
    tar.file("logs/a.txt", "hello\n"),
    # A tar header comes before its body, so the size must be known
    tar.file_stream("logs/b.txt", 9, stream.make(b"str", b"eamed\n")),
    tar.symlink("latest", "logs/b.txt"),
]
tarred = fx.run_sync(
    stream.from_iterable(tar_entries).pipe_through_channel(tar.encode()).run_bytes().or_die()
)
print(len(tarred), "bytes")
untarred = stream.make(tarred).pipe_through_channel(tar.decode()).map_effect(read_tar)
print(fx.run_sync(untarred.run_collect().or_die()))
