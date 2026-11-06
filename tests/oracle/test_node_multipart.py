"""Ports of platform-node's ``NodeMultipart.test.ts``: a body stream
parsed with ``multipart.make_channel`` (Node's ``NodeMultipart.stream``
over a ``Readable``). Each test's docstring is the Effect test title."""

import pyfect as fx
from pyfect import stream
from pyfect.exit import Failure
from pyfect.http import multipart


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
