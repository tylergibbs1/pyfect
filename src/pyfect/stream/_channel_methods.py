"""``Stream`` methods that pipe a stream through a channel: any channel
(``pipe_through_channel``), and the text channels (``decode_text``,
``encode_text``, ``split_lines``). The work is in ``pyfect.stream._text``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Never

from pyfect.stream._base import A_co, E_co, R_co, StreamBase

if TYPE_CHECKING:
    from pyfect.channel import Channel
    from pyfect.stream._stream import Stream


class ChannelMethods(StreamBase[A_co, E_co, R_co]):
    __slots__ = ()

    def pipe_through_channel[B, E2 = Never, R2 = Never](
        self, channel: Channel[tuple[B, ...], E2, object, tuple[A_co, ...], E_co, None, R2]
    ) -> Stream[B, E2, R_co | R2]:
        """The stream of what ``channel`` writes when this stream's chunks
        are its input. The channel sees this stream's failure (and decides
        what to do with it); its end value is dropped. Each tuple it writes
        must be non-empty, as for ``from_channel``."""
        from pyfect.stream import _text

        return _text.pipe_through_channel(self, channel)

    def pipe_through_channel_or_fail[B, E2 = Never, R2 = Never](
        self, channel: Channel[tuple[B, ...], E2, object, tuple[A_co, ...], Never, None, R2]
    ) -> Stream[B, E_co | E2, R_co | R2]:
        """``pipe_through_channel`` for a channel that cannot see this
        stream's failures: they pass through it untouched and fail the
        stream. Each tuple it writes must be non-empty."""
        from pyfect.stream import _text

        return _text.pipe_through_channel_or_fail(self, channel)

    def decode_text[E, R](
        self: ChannelMethods[bytes, E, R], encoding: str = "utf-8"
    ) -> Stream[str, E, R]:
        """Decode byte strings as text in ``encoding``, keeping a character
        split across byte strings whole; bad bytes become U+FFFD and a UTF-8
        byte-order mark is dropped (``channel.decode_text``)."""
        from pyfect.stream import _text

        return _text.decode_text(self, encoding)

    def encode_text[E, R](self: ChannelMethods[str, E, R]) -> Stream[bytes, E, R]:
        """Encode each string as UTF-8."""
        from pyfect.stream import _text

        return _text.encode_text(self)

    def split_lines[E, R](self: ChannelMethods[str, E, R]) -> Stream[str, E, R]:
        """Split text into lines at ``\\n``, ``\\r\\n`` and ``\\r``, wherever
        the chunks break, without the line breaks. The text after the last
        break is the last line; a trailing break adds no empty line."""
        from pyfect.stream import _text

        return _text.split_lines(self)
