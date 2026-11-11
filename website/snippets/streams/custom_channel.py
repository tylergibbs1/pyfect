from collections.abc import Callable
from typing import Never

import pyfect as fx
from pyfect import channel, pull, stream
from pyfect.channel import Channel
from pyfect.scope import CloseableScope

type Chunk = tuple[int, ...]


def keep_counting(keep: Callable[[int], bool]) -> Channel[Chunk, Never, None, Chunk, Never, None]:
    """Keep the items `keep` accepts, and say how many were dropped at the end."""

    def transform(
        upstream: fx.Effect[Chunk, fx.Done[None]], _scope: CloseableScope
    ) -> fx.Effect[fx.Effect[Chunk, fx.Done[None]]]:
        dropped = 0  # made by this run of the channel, so each run counts from 0

        @fx.gen
        def next_chunk():
            nonlocal dropped
            while True:
                # Fails with Done once the stream ends, which ends this pull as well.
                chunk = yield from upstream
                kept = tuple(n for n in chunk if keep(n))
                dropped += len(chunk) - len(kept)
                if kept:  # a stream's chunks are never empty
                    return kept

        def ended(leftover: None) -> fx.Effect[Chunk, fx.Done[None]]:
            print("dropped", dropped)
            return fx.fail(fx.Done(leftover))

        return fx.succeed(pull.catch_done(next_chunk, ended))

    return channel.from_transform(transform)


evens = (
    stream.range(1, 10).rechunk(3).pipe_through_channel_or_fail(keep_counting(lambda n: n % 2 == 0))
)
print(fx.run_blocking(evens.run_collect()))
# Running the stream again runs the channel again: the count starts from 0, not 5.
print(fx.run_blocking(evens.run_collect()))
