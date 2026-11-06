import pyfect as fx
from pyfect import sink, stream

numbers = stream.range(1, 10)

# A sink consumes a stream and produces one value.
assert fx.run_blocking(numbers.run(sink.sum())) == 55
assert fx.run_blocking(numbers.run(sink.take(3))) == [1, 2, 3]

# Streams of bytes or text: decode, split into lines, fold.
body = stream.from_iterable([b"alpha\nbe", b"ta\ngamma\n"])
lines = body.decode_text().split_lines()
assert fx.run_blocking(lines.run_fold(lambda: 0, lambda count, _line: count + 1)) == 3
