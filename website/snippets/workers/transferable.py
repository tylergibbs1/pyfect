from typing import TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect.workers import transferable


class Frame(TypedDict):
    camera: str
    pixels: bytes


# The pixels are worth moving rather than copying: say so in the schema.
Pixels = transferable.schema(S.Bytes, lambda pixels: [pixels])
FrameSchema = S.Struct(Frame, pixels=Pixels)
frame = Frame(camera="door", pixels=b"\x00\x7f\xff")


@fx.fn
def program():
    # Encoding with a Collector in the context gathers what the schemas report.
    collector = yield from transferable.make_collector
    encoded = yield from S.encode_effect(FrameSchema)(frame).pipe(
        fx.provide_service(transferable.Collector, collector)
    )
    print("encoded", encoded)
    print("to transfer", (yield from collector.clear()))
    # Without a Collector, the schema encodes as the one it wraps.
    print("plain", (yield from S.encode_effect(FrameSchema)(frame)))


fx.run_main(program())
