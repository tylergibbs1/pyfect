"""Functions combining any number of streams: ``merge_all``,
``zip_latest_all`` and ``race_all``. Each uses one shared error and
service type for all its streams."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Never, overload

from pyfect.stream._base import StreamBase, require_stream, require_streams

if TYPE_CHECKING:
    from pyfect._concurrency import Concurrency
    from pyfect.stream._stream import Stream


def merge_all[A, EE = Never, RR = Never](
    streams: Iterable[StreamBase[A, EE, RR]], *, concurrency: Concurrency, buffer_size: int = 16
) -> Stream[A, EE, RR]:
    """Run ``streams``, up to ``concurrency`` at once, writing their items
    as they come (at most ``buffer_size`` waiting)."""
    from pyfect.stream._constructors import from_iterable

    parts = list(streams)
    for part in parts:
        require_stream(part, "streams")
    return from_iterable(parts).flatten(concurrency=concurrency, buffer_size=buffer_size)


@overload
def zip_latest_all() -> Stream[Never]: ...
@overload
def zip_latest_all[A1, EE = Never, RR = Never](
    s1: StreamBase[A1, EE, RR], /
) -> Stream[tuple[A1], EE, RR]: ...
@overload
def zip_latest_all[A1, A2, EE = Never, RR = Never](
    s1: StreamBase[A1, EE, RR], s2: StreamBase[A2, EE, RR], /
) -> Stream[tuple[A1, A2], EE, RR]: ...
@overload
def zip_latest_all[A1, A2, A3, EE = Never, RR = Never](
    s1: StreamBase[A1, EE, RR], s2: StreamBase[A2, EE, RR], s3: StreamBase[A3, EE, RR], /
) -> Stream[tuple[A1, A2, A3], EE, RR]: ...
@overload
def zip_latest_all[A, EE = Never, RR = Never](
    *streams: StreamBase[A, EE, RR],
) -> Stream[tuple[A, ...], EE, RR]: ...
def zip_latest_all(*streams: StreamBase[Any, Any, Any]) -> Stream[Any, Any, Any]:
    """Once every stream has written, write a tuple of each one's latest
    item whenever any writes; end when any ends (at once if one ends
    without writing)."""
    from pyfect.stream import _constructors, _zipping

    require_streams(streams, "streams")
    if not streams:
        return _constructors.empty
    return _zipping.zip_latest_all(*streams)


def race_all[A, EE = Never, RR = Never](*streams: StreamBase[A, EE, RR]) -> Stream[A, EE, RR]:
    """The stream that writes first; the others are interrupted."""
    from pyfect.stream import _zipping

    require_streams(streams, "streams")
    return _zipping.race_all(*streams)
