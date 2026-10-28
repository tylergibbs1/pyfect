"""Splitting a byte stream on a needle (the multipart boundary), across
chunks: each run of bytes between needles goes to the callback with the
number of needles seen before it."""

from __future__ import annotations

from collections.abc import Callable


class Search:
    __slots__ = (
        "_callback",
        "_first_byte",
        "_indexes",
        "_match_index",
        "_min_chunk_length",
        "_needle",
        "_previous",
        "_seed",
    )

    def __init__(
        self,
        needle: bytes,
        callback: Callable[[int, bytes], None],
        seed: bytes | None = None,
        minimum_chunk_length: int | None = None,
    ) -> None:
        self._needle = needle
        self._callback = callback
        self._min_chunk_length = (
            len(needle) if minimum_chunk_length is None else minimum_chunk_length
        )
        indexes: dict[int, list[int]] = {}
        for i, byte in enumerate(needle):
            indexes.setdefault(byte, []).append(i)
        self._indexes = indexes
        self._first_byte = needle[0]
        self._seed = seed
        self._previous: bytes | None = seed
        self._match_index = 0

    def write(self, chunk: bytes) -> None:
        if self._previous is not None:
            chunk = self._previous + chunk
            self._previous = None
        length = len(chunk)
        needle = self._needle
        pos = 0
        while pos < length:
            remaining = length - pos
            if remaining < self._min_chunk_length:
                self._previous = chunk[pos:]
                return
            found = chunk.find(needle, pos)
            if found > -1:
                if found > pos:
                    self._callback(self._match_index, chunk[pos:found])
                self._match_index += 1
                pos = found + len(needle)
                continue
            last = chunk[length - 1]
            indexes = self._indexes.get(last)
            if indexes is not None:
                earliest = -1
                for i, index in enumerate(indexes):
                    at = length - 1 - index
                    if at >= 0 and chunk[at] == self._first_byte and i > earliest:
                        earliest = index
                if earliest == -1:
                    self._callback(self._match_index, chunk[pos:])
                else:
                    if length - 1 - earliest > pos:
                        self._callback(self._match_index, chunk[pos : length - 1 - earliest])
                    self._previous = chunk[length - 1 - earliest :]
            else:
                self._callback(self._match_index, chunk[pos:])
            break

    def end(self) -> None:
        if self._previous is not None and self._previous is not self._seed:
            self._callback(self._match_index, self._previous)
        self._previous = self._seed
        self._match_index = 0
