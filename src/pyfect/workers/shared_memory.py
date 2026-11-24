"""Typed arrays in shared memory, for passing data to workers without copying
(Effect's ``SharedMemory``).

``make(kind, length)`` allocates a zero-filled ``SharedArray`` in a
``multiprocessing.shared_memory`` segment, and ``schema(kind)`` is the payload
field that carries it in a worker message. Unlike a copied message, every worker
that gets the array reads and writes the same memory as the sender.

Both Python platforms share it. A thread worker gets the array itself. A process
worker's message carries only the segment's name, and the worker maps the segment
when the message arrives, so its writes land in the sender's array. (In Effect a
child process gets a copy, so its schema rejects it there.)

- The scope that ran ``make`` frees the segment when it closes, however it closes.
  A worker's mapping never frees it. If the process that made it dies first,
  Python's resource tracker frees it.
- Workers writing the same elements race: give each its own range.
- A field declared as ``S.Bytes`` or a list is copied, and a worker's writes to it
  are lost. Use ``schema`` for shared fields.
"""

from __future__ import annotations

import importlib
import struct
import weakref
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeIs, cast, overload

from pyfect import schema as S
from pyfect._core import Effect
from pyfect.effect import fail, succeed, suspend, sync
from pyfect.errors import TaggedError
from pyfect.scope import Scope, acquire_release
from pyfect.workers._passthrough import passthrough_link

if TYPE_CHECKING:
    from multiprocessing.shared_memory import SharedMemory


@dataclass(frozen=True, slots=True)
class Kind[T: int | float]:
    """The element type of a ``SharedArray``: one of ``int8`` ... ``float64``
    (Effect's typed array constructors)."""

    name: str
    code: str
    """The ``array`` / ``struct`` type code."""

    @property
    def item_size(self) -> int:
        return struct.calcsize(self.code)


int8: Kind[int] = Kind("int8", "b")
uint8: Kind[int] = Kind("uint8", "B")
int16: Kind[int] = Kind("int16", "h")
uint16: Kind[int] = Kind("uint16", "H")
int32: Kind[int] = Kind("int32", "i")
uint32: Kind[int] = Kind("uint32", "I")
int64: Kind[int] = Kind("int64", "q")
uint64: Kind[int] = Kind("uint64", "Q")
float32: Kind[float] = Kind("float32", "f")
float64: Kind[float] = Kind("float64", "d")


@dataclass(eq=False)
class SharedMemoryError(TaggedError):
    """``make`` could not allocate shared memory: the platform has none, or the
    system refused a segment."""

    message: str
    cause: object = None


def _segments() -> type[SharedMemory] | None:
    # Imported when used: Emscripten and WASI builds have no shared memory, and
    # importing ``pyfect.workers`` must still work there.
    try:
        module = importlib.import_module("multiprocessing.shared_memory")
    except ImportError:
        return None
    return cast("type[SharedMemory]", module.SharedMemory)


def is_available() -> bool:
    """Whether this platform has shared memory (all but Emscripten and WASI)."""
    return _segments() is not None


def _detach(view: memoryview[Any], segment: SharedMemory) -> None:
    view.release()
    segment.close()


class SharedArray[T: int | float](Sequence[T]):
    """A fixed-length array of ``kind`` elements in shared memory (Effect's
    ``Shared<A>``), indexed like a list. Made by ``make``.

    Workers on other threads index the one view the array holds, and no view is
    ever made from it: free-threaded CPython counts a buffer's views without a
    lock (``tests/test_memoryview_ownership.py``), so a slice reads and writes
    element by element and no ``memoryview`` of the array is handed out."""

    __slots__ = ("__weakref__", "_kind", "_length", "_name", "_view")

    def __init__(self, kind: Kind[T], length: int, name: str, view: memoryview[Any]) -> None:
        self._kind = kind
        self._length = length
        self._name = name
        self._view = view

    @property
    def kind(self) -> Kind[T]:
        return self._kind

    @property
    def name(self) -> str:
        """The segment's name, as ``multiprocessing.shared_memory`` names it."""
        return self._name

    def __len__(self) -> int:
        return self._length

    @overload
    def __getitem__(self, index: int) -> T: ...
    @overload
    def __getitem__(self, index: slice) -> list[T]: ...
    def __getitem__(self, index: int | slice) -> T | list[T]:
        if isinstance(index, slice):
            return [cast("T", self._view[i]) for i in range(*index.indices(self._length))]
        return cast("T", self._view[index])

    @overload
    def __setitem__(self, index: int, value: T) -> None: ...
    @overload
    def __setitem__(self, index: slice, value: Iterable[T]) -> None: ...
    def __setitem__(self, index: int | slice, value: T | Iterable[T]) -> None:
        if isinstance(index, slice):
            positions = range(*index.indices(self._length))
            values = list(cast("Iterable[T]", value))
            if len(values) != len(positions):
                raise ValueError(f"{len(values)} values for a slice of {len(positions)}")
            for i, item in zip(positions, values, strict=True):
                self._view[i] = item
        else:
            self._view[index] = cast("Any", value)

    def __iter__(self) -> Iterator[T]:
        return iter(self.tolist())

    def tolist(self) -> list[T]:
        return cast("list[T]", self._view.tolist())

    def __reduce__(self) -> tuple[Any, ...]:
        # A message carries the segment's name; the receiver maps the segment.
        try:
            self._view.nbytes  # noqa: B018 - raises once released
        except ValueError:
            raise ValueError(f"{self!r} is closed: its scope has freed it") from None
        return (_attach, (self._kind, self._length, self._name))

    def __repr__(self) -> str:
        return f"SharedArray({self._kind.name}, {self._length}, name={self._name!r})"


@dataclass(frozen=True, slots=True)
class _Opened[T: int | float]:
    shared: SharedArray[T]
    segment: SharedMemory
    detach: weakref.finalize[[memoryview[Any], SharedMemory], SharedArray[T]]

    def free(self) -> None:
        self.detach()
        self.segment.unlink()


def _open[T: int | float](kind: Kind[T], length: int, segment: SharedMemory) -> _Opened[T]:
    mapped = cast("memoryview[Any]", segment.buf)
    bytes_view: Any = mapped[: length * kind.item_size]
    view = cast("memoryview[Any]", bytes_view.cast(kind.code))
    shared = SharedArray(kind, length, segment.name, view)
    # Unmapped when the array is collected, or when its scope frees it.
    return _Opened(shared, segment, weakref.finalize(shared, _detach, view, segment))


def _attach[T: int | float](kind: Kind[T], length: int, name: str) -> SharedArray[T]:
    segments = _segments()
    assert segments is not None  # the sender had shared memory, so this platform does
    # Not tracked: a worker that maps the segment must not free it when it exits.
    return _open(kind, length, segments(name, track=False)).shared


def _allocate[T: int | float](kind: Kind[T], length: int) -> Effect[_Opened[T], SharedMemoryError]:
    segments = _segments()
    if segments is None:
        return fail(SharedMemoryError(message="multiprocessing.shared_memory is unavailable here"))
    try:
        # Tracked, so Python's resource tracker frees it if this process dies first.
        # A segment can't be empty: a zero-length array maps one byte and uses none.
        segment = segments(create=True, size=max(length * kind.item_size, 1))
    except OSError as cause:
        return fail(SharedMemoryError(message="could not allocate shared memory", cause=cause))
    return succeed(_open(kind, length, segment))


def make[T: int | float](
    kind: Kind[T], length: int
) -> Effect[SharedArray[T], SharedMemoryError, Scope]:
    """A zero-filled array of ``length`` ``kind`` elements in shared memory,
    freed when the scope closes. Fails with ``SharedMemoryError`` when the
    platform has no shared memory or refuses a segment."""
    if length < 0:
        raise ValueError(f"a shared array's length can't be negative, got {length}")
    opened = acquire_release(
        suspend(lambda: _allocate(kind, length)), lambda opened, _: sync(opened.free)
    )
    return opened.map(lambda opened: opened.shared)


def is_shared(value: object) -> TypeIs[SharedArray[Any]]:
    """Whether ``value`` is an array in shared memory."""
    return isinstance(value, SharedArray)


def schema[T: int | float](kind: Kind[T]) -> S.Bottom[SharedArray[T]]:
    """A worker message field holding a ``kind`` array in shared memory. It
    accepts only a ``SharedArray`` of ``kind``, so a copy fails rather than
    losing the worker's writes, and ``S.to_codec_json`` passes the array
    through unchanged, as worker codecs need."""

    def guard(value: object) -> TypeIs[SharedArray[T]]:
        return isinstance(value, SharedArray) and cast("SharedArray[Any]", value).kind == kind

    return S.declare(
        guard, expected=f"{kind.name} array in shared memory", to_codec_json=passthrough_link
    )


__all__ = [
    "Kind",
    "SharedArray",
    "SharedMemoryError",
    "float32",
    "float64",
    "int8",
    "int16",
    "int32",
    "int64",
    "is_available",
    "is_shared",
    "make",
    "schema",
    "uint8",
    "uint16",
    "uint32",
    "uint64",
]
