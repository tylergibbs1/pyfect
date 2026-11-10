"""pyfect-specific platform behaviour: Python inputs, the live services
against real files and streams, and ports of Effect features with no test of
their own (``layerNoop``, ``Logger.toFile``, ``PlatformError`` messages)."""

import errno
import io
import os
import time
from datetime import datetime
from pathlib import Path as FsPath

import pytest

import pyfect as fx
from pyfect import file_system, logger, path, platform, stdio, stream, terminal, testing
from pyfect.file_system import FileSystem, NoopFileSystem
from pyfect.file_system._stat import file_info
from pyfect.path import Path
from pyfect.platform_error import (
    BadArgument,
    BadResource,
    NotFound,
    PermissionDenied,
    PlatformError,
    Unknown,
    bad_argument,
    from_exception,
    system_error,
    tag_of,
)
from pyfect.terminal import Key, TerminalService, UserInput
from pyfect.terminal._keys import decode
from pyfect.testing import Services

live_fs = testing.layer_fixture(file_system.layer)


# --- PlatformError --------------------------------------------------------------------


def test_a_system_error_message_names_the_tag_method_path_and_description():
    error = system_error(
        "NotFound",
        module="FileSystem",
        method="read_file",
        path_or_descriptor="/a",
        description="gone",
    )
    assert error.message == "NotFound: FileSystem.read_file (/a): gone"
    assert isinstance(error.reason, NotFound)
    assert bad_argument(module="Path", method="join").message == "Path.join"


def test_the_platform_error_carries_its_reasons_cause():
    cause = ValueError("x")
    assert bad_argument(module="M", method="m", cause=cause).cause is cause


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        (errno.ENOENT, NotFound),
        (errno.EACCES, PermissionDenied),
        (errno.EPERM, PermissionDenied),
        (errno.ENOTDIR, BadResource),
        (errno.EIO, Unknown),
    ],
)
def test_os_errors_are_tagged_by_errno(code: int, reason: type[PlatformError]):
    error = from_exception(OSError(code, os.strerror(code)), module="FileSystem", method="stat")
    assert type(error.reason) is reason
    assert error.reason.tag == tag_of(OSError(code, ""))


def test_other_exceptions_become_bad_arguments():
    error = from_exception(ValueError("embedded null byte"), module="FileSystem", method="stat")
    assert isinstance(error.reason, BadArgument)


# --- Path -----------------------------------------------------------------------------


def test_the_host_path_layer_matches_the_operating_system():
    p = fx.run_blocking(Path().pipe(fx.provide(path.layer)))
    assert p.sep == os.sep


def test_posix_paths_follow_node():
    p = path.posix
    assert p.join("/a", "/b") == "/a/b"
    assert p.relative("/a/b", "/a/b") == ""
    assert p.basename("/a/b.txt", ".txt") == "b"
    parsed = path.Parsed(root="/", dir="/a", base="b.txt", ext=".txt", name="b")
    assert p.parse("/a/b.txt") == parsed
    assert p.format(dir="/a", base="b.txt") == "/a/b.txt"


@testing.effect
def test_from_file_url_rejects_an_encoded_separator_and_another_scheme():
    for url in ("file:///a%2fb", "https://example.com/a", "file://host/a"):
        error = yield from path.posix.from_file_url(fx.Url(url)).flip()
        assert isinstance(error, BadArgument), url


@testing.effect
def test_from_file_url_parses_the_url_as_a_browser_does():
    # Effect takes a parsed URL: localhost is no host and dot segments are
    # resolved. Expected values printed by Node 24's fileURLToPath.
    cases = {
        "file://LocalHost/a/b": "/a/b",
        "file:///a/./b/.": "/a/b/",
        "file:///a/b/..": "/a/",
        "file:///a/%2e%2E/b": "/b",
        "file:///../../x": "/x",
        "file:///C:/../x": "/C:/x",
    }
    for url, expected in cases.items():
        assert (yield from path.posix.from_file_url(fx.Url(url))) == expected, url
    assert (yield from path.win32.from_file_url(fx.Url("file://localhost/C:/a"))) == "C:\\a"
    assert (yield from path.win32.from_file_url(fx.Url("file:///C:/../x"))) == "C:\\x"


@testing.effect
def test_win32_file_urls_handle_shares():
    share = yield from path.win32.from_file_url(fx.Url("file://server/share/a"))
    assert share == "\\\\server\\share\\a"


# --- FileSystem -----------------------------------------------------------------------


@testing.effect
def test_read_file_string_strips_a_bom_and_rejects_an_unknown_encoding(
    live_fs: Services[FileSystem], tmp_path: FsPath
):
    target = tmp_path / "bom.txt"
    target.write_bytes(b"\xef\xbb\xbfhello")
    fs = yield from FileSystem()
    assert (yield from fs.read_file_string(str(target))) == "hello"
    error = yield from fs.read_file_string(str(target), "no-such-codec").flip()
    assert isinstance(error.reason, BadArgument)
    # Codecs that are not text encodings (TextDecoder knows none of them).
    for codec in ("rot13", "base64", "zlib"):
        error = yield from fs.read_file_string(str(target), codec).flip()
        assert isinstance(error.reason, BadArgument)


@testing.effect
def test_utimes_rejects_a_naive_datetime(live_fs: Services[FileSystem], tmp_path: FsPath):
    target = tmp_path / "file"
    target.write_text("")
    fs = yield from FileSystem()
    naive = datetime(2001, 1, 1)
    error = yield from fs.utimes(str(target), naive, 0.0).flip()
    assert isinstance(error.reason, BadArgument)


# Node's fs.cp, as printed under Node 24: its ERR_FS_CP_* codes are not
# among the codes Effect tags, so they are Unknown.


@testing.effect
def test_copy_refuses_a_directory_into_itself_and_creates_nothing(
    live_fs: Services[FileSystem], tmp_path: FsPath
):
    source = tmp_path / "d"
    source.mkdir()
    (source / "f").write_text("x")
    fs = yield from FileSystem()
    into_child = yield from fs.copy(str(source), str(source / "sub")).flip()
    onto_itself = yield from fs.copy(str(source), str(source)).flip()
    assert isinstance(into_child.reason, Unknown)
    assert isinstance(onto_itself.reason, Unknown)
    assert sorted(os.listdir(source)) == ["f"]


@testing.effect
def test_copy_refuses_to_mix_files_and_directories(live_fs: Services[FileSystem], tmp_path: FsPath):
    (tmp_path / "d").mkdir()
    (tmp_path / "f").write_text("x")
    fs = yield from FileSystem()
    file_onto_directory = yield from fs.copy(
        str(tmp_path / "f"), str(tmp_path / "d"), overwrite=True
    ).flip()
    directory_onto_file = yield from fs.copy(str(tmp_path / "d"), str(tmp_path / "f")).flip()
    assert isinstance(file_onto_directory.reason, Unknown)
    assert isinstance(directory_onto_file.reason, Unknown)
    assert os.listdir(tmp_path / "d") == []


@testing.effect
def test_copy_makes_missing_parents_and_keeps_symbolic_links(
    live_fs: Services[FileSystem], tmp_path: FsPath
):
    source = tmp_path / "d"
    source.mkdir()
    (source / "f").write_text("x")
    os.symlink("f", source / "link")
    os.symlink("/nonexistent", source / "dangling")
    fs = yield from FileSystem()
    yield from fs.copy(str(source / "f"), str(tmp_path / "new" / "deep" / "f"))
    yield from fs.copy(str(source), str(tmp_path / "copy"))
    assert (tmp_path / "new" / "deep" / "f").read_text() == "x"
    assert os.readlink(tmp_path / "copy" / "link") == str(source / "f")
    assert os.readlink(tmp_path / "copy" / "dangling") == "/nonexistent"


@testing.effect
def test_glob_excludes_whole_directories_as_node_does(
    live_fs: Services[FileSystem], tmp_path: FsPath
):
    # Expected values printed by Node 24's fs.glob.
    (tmp_path / "a" / "b").mkdir(parents=True)
    for name in ("x.ts", ".hidden.ts", "a/y.ts", "a/b/z.ts"):
        (tmp_path / name).write_text("")
    fs = yield from FileSystem()
    root = str(tmp_path)
    assert (yield from fs.glob("**/*.ts", root=root, exclude=("a",))) == ["x.ts"]
    assert sorted((yield from fs.glob("**/*.ts", root=root, exclude=("a/b",)))) == [
        "a/y.ts",
        "x.ts",
    ]
    assert (yield from fs.glob("a/", root=root)) == ["a"]


def test_device_numbers_are_read_as_unsigned_64_bit():
    times = {"st_atime_ns": 0, "st_mtime_ns": 0, "st_ctime_ns": 0}
    info = file_info(os.stat_result((0o100644, -1, -2, 1, 0, 0, 0, 0, 0, 0), times))
    assert (info.ino, info.dev) == (2**64 - 1, 2**64 - 2)
    assert info.type == "File"


@testing.effect
def test_the_noop_file_system_has_nothing_in_it():
    fs = NoopFileSystem()
    assert (yield from fs.exists("/a")) is False
    yield from fs.remove("/a")
    error = yield from fs.read_file("/a").flip()
    assert isinstance(error.reason, NotFound)
    assert (error.reason.method, error.reason.path_or_descriptor) == ("read_file", "/a")
    made = yield from fs.make_temp_directory().exit()
    assert isinstance(made, fx.Failure)
    assert made.cause.has_dies


@testing.effect
def test_layer_noop_provides_a_subclass():
    class OneFile(NoopFileSystem):
        def read_file(self, path: str) -> fx.Effect[bytes, PlatformError]:
            return fx.succeed(b"data")

    program = FileSystem().flat_map(lambda fs: fs.read_file("/a"))
    assert (yield from program.pipe(fx.provide(file_system.layer_noop(OneFile())))) == b"data"


# --- Logger.to_file -------------------------------------------------------------------


def test_to_file_appends_each_batch_of_lines(tmp_path: FsPath):
    target = tmp_path / "app.log"
    target.write_text("before\n")
    lines = logger.Logger.make(lambda options: " ".join(map(str, options.message)))
    file_logger = lines.to_file(str(target), batch_window="1 minute")

    program = fx.log_info("one").and_then(fx.log_info("two", 2))
    fx.run_blocking(
        program.pipe(fx.provide(logger.layer([file_logger])))
        .pipe(fx.provide(file_system.layer))
        .or_die()
    )

    assert target.read_text() == "before\none\ntwo 2\n"


def test_to_file_writes_a_lone_surrogate_as_the_replacement_character(tmp_path: FsPath):
    # Effect encodes with TextEncoder, which writes U+FFFD for it.
    target = tmp_path / "app.log"
    lines = logger.Logger.make(lambda options: " ".join(map(str, options.message)))
    file_logger = lines.to_file(str(target), batch_window="1 minute")
    program = fx.log_info("a\ud800b").pipe(fx.provide(logger.layer([file_logger])))
    fx.run_blocking(program.pipe(fx.provide(file_system.layer)).or_die())
    assert target.read_bytes() == "a\ufffdb\n".encode()


@testing.effect
def test_to_file_fails_when_the_file_cannot_be_opened(
    live_fs: Services[FileSystem], tmp_path: FsPath
):
    lines = logger.Logger.make(lambda _options: "x")
    error = yield from lines.to_file(str(tmp_path / "missing" / "app.log")).flip()
    assert isinstance(error.reason, NotFound)


# --- Stdio ----------------------------------------------------------------------------


def test_the_live_stdout_writes_text_and_bytes(capfd: pytest.CaptureFixture[str]):
    fx.run_blocking(stream.make("text ", b"bytes\n").run(stdio.live.stdout()).or_die())
    assert capfd.readouterr().out == "text bytes\n"


def test_the_live_args_skip_the_program_name(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("sys.argv", ["prog", "a", "b"])
    assert fx.run_blocking(stdio.live.args) == ("a", "b")


def test_the_live_stdin_streams_bytes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"in\nput")))
    assert b"".join(fx.run_blocking(stdio.live.stdin.run_collect().or_die())) == b"in\nput"


# --- Terminal -------------------------------------------------------------------------


def test_keys_are_named_as_node_readline_names_them():
    assert decode("a") == [UserInput("a", Key("a"))]
    assert decode("A") == [UserInput("A", Key("a", shift=True))]
    assert decode("\x03") == [UserInput("\x03", Key("c", ctrl=True))]
    assert decode("\x1b[A") == [UserInput(None, Key("up"))]
    assert decode("\x1b[1;5C") == [UserInput(None, Key("right", ctrl=True))]
    assert decode("\x1b[3~") == [UserInput(None, Key("delete"))]
    assert decode("\r") == [UserInput("\r", Key("return"))]


def test_keys_follow_node_readline_where_it_differs_from_a_plain_reading():
    # Each case printed by readline.emitKeypressEvents under Node 24.
    assert decode("\x1bx") == [UserInput(None, Key("x", meta=True))]
    assert decode("\x1b.") == [UserInput(None, Key("", meta=True))]
    assert decode("\x1b\x1b") == [UserInput(None, Key("escape", meta=True))]
    assert decode("\x1b\x1b[A") == [UserInput(None, Key("up"))]
    assert decode("\x1b[9z") == [UserInput(None, Key("undefined", meta=True))]
    assert decode("\x1c.") == [UserInput("\x1c", Key("")), UserInput(".", Key(""))]
    assert decode("\x00") == [UserInput("\x00", Key("`", ctrl=True))]
    assert decode("a\r\nb") == [
        UserInput("a", Key("a")),
        UserInput("\r", Key("return")),
        UserInput("\n", Key("enter")),
        UserInput("b", Key("b")),
    ]
    # An unfinished sequence waits for the rest; only a trailing ESC times out.
    assert decode("\x1b[") == []
    assert decode("a\x1b") == [UserInput("a", Key("a")), UserInput(None, Key("escape", meta=True))]


@testing.live(timeout="10 seconds")
def test_an_escape_sequence_split_across_reads_is_one_key():
    # Node's readline keeps a partial sequence across reads, and takes a
    # trailing ESC for the escape key once 50 ms pass without more input.
    read_end, write_end = os.pipe()
    yield from fx.acquire_release(
        fx.succeed(None), lambda _a, _e: fx.sync(lambda: (os.close(read_end), os.close(write_end)))
    )
    service = terminal.live(should_quit=lambda _: False, input=read_end, output=io.StringIO())
    queue = yield from service.read_input
    os.write(write_end, b"\x1b")
    yield from fx.sleep("10 millis")
    os.write(write_end, b"[A")
    assert (yield from queue.take()) == UserInput(None, Key("up"))
    os.write(write_end, b"\x1b[")
    yield from fx.sleep("100 millis")
    os.write(write_end, b"B")
    assert (yield from queue.take()) == UserInput(None, Key("down"))
    os.write(write_end, b"\x1b")
    yield from fx.sleep("100 millis")
    os.write(write_end, b"a")
    assert (yield from queue.take()) == UserInput(None, Key("escape", meta=True))
    assert (yield from queue.take()) == UserInput("a", Key("a"))


@testing.live
def test_concurrent_reads_keep_input_in_order(monkeypatch: pytest.MonkeyPatch):
    read_end, write_end = os.pipe()
    os.write(write_end, b"first\n")
    real_read = os.read
    delayed: list[bool] = []

    def slow_first_read(fd: int, size: int) -> bytes:
        data = real_read(fd, size)
        if fd == read_end and not delayed:
            delayed.append(True)
            # A second reader takes this while the first still holds its bytes.
            os.write(write_end, b"second\n")
            time.sleep(0.2)
        return data

    monkeypatch.setattr(os, "read", slow_first_read)
    service = terminal.live(input=read_end, output=io.StringIO())
    finished: list[str] = []
    record = service.read_line.tap(lambda line: fx.sync(lambda: finished.append(line)))
    try:
        yield from fx.all(record, record, concurrency=2)
    finally:
        os.close(read_end)
        os.close(write_end)
    assert finished == ["first", "second"]


def test_display_writes_to_the_output():
    output = io.StringIO()
    fx.run_blocking(terminal.live(input=0, output=output).display("prompt> ").or_die())
    assert output.getvalue() == "prompt> "


@testing.effect
def test_a_display_failure_is_a_bad_argument():
    output = io.StringIO()
    output.close()
    error = yield from terminal.live(input=0, output=output).display("x").flip()
    assert isinstance(error.reason, BadArgument)
    assert error.reason.description == "Failed to write prompt to stdout"


def test_the_platform_layer_provides_every_service():
    program = fx.all(FileSystem(), Path(), fx.Stdio(), fx.Terminal())
    services = fx.run_blocking(program.pipe(fx.provide(platform.layer)))
    assert len(services) == 4


def test_services_reject_a_non_effect_field():
    with pytest.raises(TypeError, match=r"^rows must be an Effect"):
        TerminalService(
            columns=fx.succeed(0),
            rows=0,  # pyright: ignore[reportArgumentType]
            size=terminal.live(input=0).size,
            read_input=terminal.live(input=0).read_input,
            read_line=fx.succeed(""),
            display=lambda _text: fx.void,
        )
