import sys

import pytest
from checksums import checksum, parse_port

import pyfect as fx
from pyfect import interpreter_pool
from pyfect.errors import UnknownError

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 14), reason="needs Python 3.14's concurrent.interpreters"
)


def test_checksums_run_in_subinterpreters() -> None:
    blobs = [bytes([i]) * 100_000 for i in range(4)]
    program = fx.all(*[interpreter_pool.call(checksum, blob) for blob in blobs], concurrency=4)
    sums = fx.run_blocking(program.pipe(fx.provide(interpreter_pool.layer(size=4))))
    assert list(sums) == [checksum(blob) for blob in blobs]


def test_a_raised_exception_comes_back() -> None:
    parsed = interpreter_pool.try_call(parse_port, "70000").pipe(
        fx.catch_tag(UnknownError, lambda e: fx.succeed(str(e.cause)))
    )
    message = fx.run_blocking(parsed.pipe(fx.provide(interpreter_pool.layer(size=1))))
    assert message == "port out of range: 70000"
