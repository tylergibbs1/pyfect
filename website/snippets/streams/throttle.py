import pyfect as fx
from pyfect import stream


def enforce(chunks: stream.Stream[int], *, burst: int = 0) -> list[int]:
    """What a bucket of 3 units a minute, plus `burst`, lets through at once."""
    throttled = chunks.throttle(
        cost=len, units=3, burst=burst, duration="1 minute", strategy="enforce"
    )
    return list(fx.run_blocking(throttled.run_collect()))


# The bucket holds up to units + burst = 6 tokens, but starts with units = 3.
print(enforce(stream.make(1, 2, 3, 4, 5, 6).rechunk(1), burst=3))
# "enforce" keeps or drops whole chunks: (3, 4) costs 2 with 1 token left.
print(enforce(stream.make(1, 2, 3, 4, 5).rechunk(2)))
