"""Ports of the ``encoding`` section of Effect's ``Stream.test.ts``:
``decodeText`` and ``splitLines``.

Each test's docstring is the Effect test title. ``Uint8Array`` is
``bytes`` and ``Stream.mkString`` is ``run_string``.

Adapted, with the reason:

- "matches String.linesIterator regardless of chunk boundaries" is a
  property test over a Schema arbitrary; Schema's arbitraries come with M8,
  so the port checks 2000 seeded random chunk lists of the same shape (at
  most 8 strings of at most 8 characters from ``a``, ``b``, ``\\n``,
  ``\\r``) against ``str.splitlines``, which agrees with
  ``linesIterator`` on those characters.
"""

import random

import pyfect as fx
from pyfect import stream, testing
from pyfect.pull import Pull


def _split_lines(chunks: list[str]) -> fx.Effect[list[str]]:
    return stream.from_iterable(chunks).split_lines().run_collect()


# --- decodeText -------------------------------------------------------------------


@testing.effect
def test_decode_text_handles_multi_byte_characters_split_across_chunks():
    """decodeText handles multi-byte characters split across chunks"""
    data = "🌍".encode()
    result = yield from stream.make(data[:2], data[2:]).decode_text().run_string()
    assert result == "🌍"


@testing.effect
def test_decode_text_handles_mixed_ascii_and_multi_byte_characters_across_chunks():
    """decodeText handles mixed ASCII and multi-byte characters across chunks"""
    data = "Hello 🌍!".encode()
    result = yield from stream.make(data[:8], data[8:]).decode_text().run_string()
    assert result == "Hello 🌍!"


# --- splitLines -------------------------------------------------------------------


@testing.effect
def test_handles_an_empty_stream():
    """handles an empty stream"""
    assert (yield from _split_lines([])) == []


@testing.effect
def test_handles_empty_chunks_and_repeated_line_feeds():
    """handles empty chunks and repeated line feeds"""
    assert (yield from _split_lines(["", "a\n\n", "", "b\n", ""])) == ["a", "", "b"]


@testing.effect
def test_handles_line_feeds_across_chunks():
    """handles line feeds across chunks"""
    assert (yield from _split_lines(["a\nb", "\nc\n", "d"])) == ["a", "b", "c", "d"]


@testing.effect
def test_handles_carriage_return_line_feed_pairs_across_chunks():
    """handles carriage return / line feed pairs across chunks"""
    assert (yield from _split_lines(["a\r", "\nb\r", "\nc"])) == ["a", "b", "c"]


@testing.effect
def test_emits_a_carriage_return_terminated_line_before_pulling_upstream_again():
    """emits a carriage-return-terminated line before pulling upstream again"""
    lines = stream.succeed("a\r").concat(stream.fail("boom")).split_lines()
    result = yield from lines.take(1).run_collect().result()
    assert result == fx.Ok(["a"])


@testing.effect
def test_emits_the_final_line_when_the_stream_does_not_end_with_a_newline():
    """emits the final line when the stream does not end with a newline"""
    assert (yield from _split_lines(["a\nb\nc\n", "d\ne"])) == ["a", "b", "c", "d", "e"]


@testing.effect
def test_does_not_pull_upstream_again_after_flushing_the_final_line():
    """does not pull upstream again after flushing the final line"""
    pulls = 0

    def make() -> Pull[tuple[str, ...], str]:
        def pull() -> Pull[tuple[str, ...], str]:
            nonlocal pulls
            pulls += 1
            if pulls == 1:
                return fx.succeed(("a",))
            if pulls == 2:
                return fx.fail(fx.Done())
            return fx.fail("pulled after done")

        return fx.suspend(pull)

    result = yield from stream.from_pull(fx.sync(make)).split_lines().run_collect()
    assert result == ["a"]
    assert pulls == 2


@testing.effect
def test_handles_standalone_carriage_returns_within_a_chunk():
    """handles standalone carriage returns within a chunk"""
    assert (yield from _split_lines(["a\rb\rc"])) == ["a", "b", "c"]


@testing.effect
def test_handles_standalone_carriage_returns_across_chunk_boundaries():
    """handles standalone carriage returns across chunk boundaries"""
    assert (yield from _split_lines(["a\r", "b\r", "c"])) == ["a", "b", "c"]


@testing.effect
def test_matches_string_lines_iterator_regardless_of_chunk_boundaries():
    """matches String.linesIterator regardless of chunk boundaries"""
    rng = random.Random(4)
    for _ in range(2000):
        chunks = [
            "".join(rng.choice("ab\n\r") for _ in range(rng.randint(0, 8)))
            for _ in range(rng.randint(0, 8))
        ]
        assert (yield from _split_lines(chunks)) == "".join(chunks).splitlines(), chunks
