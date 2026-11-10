"""Ports of platform-node's ``NodeMultipart.test.ts``: a body stream
parsed with ``multipart.make_channel`` (Node's ``NodeMultipart.stream``
over a ``Readable``). Each test's docstring is the Effect test title.

Adapted, with the reason: a body source here is a pull ``Stream``, not a
Node ``Readable`` with listeners. "Removes its source listeners" is the
source stream's release once parsing ends; "leaves the source open on
interruption" is an interrupted parse that ends without failing the
source's own later error into it. A source's own failure reaches the
parse as that failure (``make_channel`` passes upstream errors through, as
Effect's ``Multipart.makeChannel`` does); the conversion of a ``Readable``
error to ``Parse`` is ``NodeMultipart``'s own over Node streams.
"""

import pyfect as fx
from pyfect import effect, stream
from pyfect.cause import Interrupt
from pyfect.exit import Failure
from pyfect.http import multipart

HEADERS = {"content-type": "multipart/form-data; boundary=x"}
FORM = b'--x\r\nContent-Disposition: form-data; name="a"\r\n\r\nb\r\n--x--\r\n'


def _parts[E](body: fx.Stream[bytes, E]) -> fx.Stream[multipart.Part, multipart.MultipartError | E]:
    return body.pipe_through_channel(multipart.make_channel(HEADERS))


def _drain_files(part: multipart.Part) -> fx.Effect[None, multipart.MultipartError]:
    return part.content.run_drain() if isinstance(part, multipart.File) else effect.void


def test_fails_with_a_typed_parse_error_when_the_boundary_is_missing() -> None:
    """fails with a typed parse error when the boundary is missing"""
    body = stream.make(b'--x\r\nContent-Disposition: form-data; name="a"\r\n\r\n1\r\n--x--\r\n')
    parts = body.pipe_through_channel(
        multipart.make_channel({"content-type": "multipart/form-data"})
    )
    exit = fx.run_blocking_exit(parts.run_collect())
    assert isinstance(exit, Failure)
    error = exit.cause.squash()
    assert isinstance(error, multipart.MultipartError)
    assert error.reason.tag == "Parse"


def test_removes_its_source_listeners_after_parsing() -> None:
    """removes its source listeners after parsing"""
    released: list[str] = []
    body = stream.make(FORM).ensuring(effect.sync(lambda: released.append("source")))
    fx.run_blocking(_parts(body).run_drain().or_die())
    assert released == ["source"]


def test_fails_with_a_typed_parse_error_when_the_source_terminates_early() -> None:
    """fails with a typed parse error when the source terminates early"""
    cause = RuntimeError("boom")
    failed = fx.run_blocking_exit(_parts(stream.fail(cause)).run_drain())
    assert isinstance(failed, Failure)
    assert failed.cause.squash() is cause

    # The source ends in the middle of a file's content.
    closed = stream.make(
        b'--x\r\nContent-Disposition: form-data; name="a"; filename="a.txt"\r\n\r\nb'
    )
    exit = fx.run_blocking_exit(_parts(closed).run_for_each(_drain_files))
    assert isinstance(exit, Failure)
    error = exit.cause.squash()
    assert isinstance(error, multipart.MultipartError)
    assert error.reason.tag == "Parse"


def test_leaves_the_source_open_on_interruption_and_handles_its_later_error() -> None:
    """leaves the source open on interruption and handles its later error"""
    released: list[str] = []
    # Part of a form, then a source that fails only later.
    body = (
        stream.make(FORM[:20])
        .concat(stream.from_effect(fx.sleep("1 hour").flat_map(lambda _: effect.fail("late"))))
        .ensuring(effect.sync(lambda: released.append("source")))
    )

    @fx.fn
    def program():
        fiber = yield from _parts(body).run_drain().fork()
        yield from effect.yield_now()
        yield from fiber.interrupt()
        return (yield from fiber.await_exit())

    exit = fx.run_blocking(program())
    assert isinstance(exit, Failure)
    assert all(isinstance(reason, Interrupt) for reason in exit.cause.reasons)
    assert released == ["source"]
