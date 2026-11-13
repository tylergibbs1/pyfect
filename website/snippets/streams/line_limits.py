"""Bounding the lines a peer can send: the stream fails instead of holding a line forever."""

import pyfect as fx
from pyfect import stream
from pyfect.encoding import ndjson

# A peer that sends text and never a line break.
endless = stream.succeed("x" * 1024).forever()

lines = endless.split_lines_within(64 * 1024)
print(fx.run_blocking(lines.run_drain().flip().or_die()))

values = endless.pipe_through_channel(ndjson.decode_string(max_line_length=64 * 1024))
print(fx.run_blocking(values.run_drain().flip().or_die()).reason)
