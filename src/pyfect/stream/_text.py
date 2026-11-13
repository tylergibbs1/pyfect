"""The work behind ``Stream``'s channel and text methods: each pipes the
stream's channel through another channel."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any

from pyfect.channel import Channel
from pyfect.channel import decode_text as channel_decode_text
from pyfect.channel import encode_text as channel_encode_text
from pyfect.channel import split_lines as channel_split_lines
from pyfect.channel import split_lines_within as channel_split_lines_within
from pyfect.channel._base import require_channel
from pyfect.stream._base import AnyStream
from pyfect.stream._stream import Stream

type AnyChannel = Channel[Any, Any, Any, Any, Any, Any, Any]
type AnyStream_ = Stream[Any, Any, Any]


def pipe_through_channel(self: AnyStream, channel: AnyChannel) -> AnyStream_:
    require_channel(channel, "channel")
    return Stream(self._channel.pipe_to(channel))


def pipe_through_channel_or_fail(self: AnyStream, channel: AnyChannel) -> AnyStream_:
    require_channel(channel, "channel")
    return Stream(self._channel.pipe_to_or_fail(channel))


def decode_text(self: AnyStream, encoding: str) -> AnyStream_:
    decoder: AnyChannel = channel_decode_text(encoding)
    return Stream(self._channel.pipe_to(decoder))


def encode_text(self: AnyStream) -> AnyStream_:
    encoder: AnyChannel = channel_encode_text()
    return Stream(self._channel.pipe_to(encoder))


def split_lines(self: AnyStream) -> AnyStream_:
    splitter: AnyChannel = channel_split_lines()
    return Stream(self._channel.pipe_to(splitter))


def split_lines_within(self: AnyStream, max_length: int) -> AnyStream_:
    splitter: AnyChannel = channel_split_lines_within(max_length)
    return Stream(self._channel.pipe_to(splitter))
