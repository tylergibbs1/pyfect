"""The replay buffer of a ``PubSub`` and the window a new subscriber reads.

The buffer keeps the last ``capacity`` published messages, whether or not
anyone is subscribed. A subscriber starts with a ``ReplayWindow``: a
snapshot of those messages, read before anything published after it
subscribed.

While the window is not drained, the subscriber has read nothing else, so a
message slid out of the hub before the subscriber read it would leave a gap
between the window and the subscription. The buffer logs each slid message
with its publish index, and the window shifts forward over the ones newer
than its own newest message (Effect's ``ReplayWindowImpl.sync``): the
subscriber still reads one unbroken run of messages.
"""

from __future__ import annotations

from collections import deque

from pyfect.option import Option, Some


class ReplayBuffer[A]:
    __slots__ = ("_next_index", "capacity", "items", "slide_count", "slides")

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.items: deque[tuple[int, A]] = deque(maxlen=capacity)
        self._next_index = 0
        self.slides: deque[tuple[int, A]] = deque(maxlen=capacity)
        self.slide_count = 0

    def offer(self, value: A) -> int:
        """Keep ``value`` (dropping the oldest past capacity); its index."""
        index = self._next_index
        self._next_index += 1
        self.items.append((index, value))
        return index

    def slide(self, value: A, index: int) -> None:
        """Log that the message published at ``index`` slid out of the hub."""
        self.slides.append((index, value))
        self.slide_count += 1


class ReplayWindow[A]:
    """The replayed messages a subscription reads first."""

    __slots__ = ("_buffer", "_newest", "_slides_seen", "_values")

    def __init__(self, buffer: ReplayBuffer[A] | None) -> None:
        self._buffer = buffer
        self._values: deque[A] = deque()
        self._newest = -1
        self._slides_seen = 0
        if buffer is not None:
            for index, value in buffer.items:
                self._values.append(value)
                self._newest = index
            self._slides_seen = buffer.slide_count

    @property
    def remaining(self) -> int:
        return len(self._values)

    def take(self) -> Option[A]:
        """The next replayed message; ``None`` once drained."""
        if not self._values:
            return None
        self._sync()
        value = self._values.popleft()
        if not self._values:
            self.close()
        return Some(value)

    def take_n(self, n: int) -> list[A]:
        """Up to ``n`` replayed messages (none if ``n`` is 0 or less)."""
        if not self._values or n <= 0:
            return []
        self._sync()
        values = [self._values.popleft() for _ in range(min(n, len(self._values)))]
        if not self._values:
            self.close()
        return values

    def take_all(self) -> list[A]:
        return self.take_n(len(self._values))

    def close(self) -> None:
        """Drop what is left; a drained window keeps nothing alive."""
        self._values.clear()
        self._buffer = None

    def _sync(self) -> None:
        buffer = self._buffer
        if buffer is None:
            return
        slides = buffer.slide_count - self._slides_seen
        self._slides_seen = buffer.slide_count
        if slides == 0:
            return
        logged = list(buffer.slides)
        for index, value in logged[len(logged) - min(slides, len(logged)) :]:
            if index > self._newest:
                self._values.popleft()
                self._values.append(value)
                self._newest = index
