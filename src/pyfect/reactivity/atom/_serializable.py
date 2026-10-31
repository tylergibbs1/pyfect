"""Serializable atoms (for ``Hydration``) and server values."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Never, cast

from pyfect.reactivity import async_result
from pyfect.reactivity.atom._types import Atom

if TYPE_CHECKING:
    from pyfect.reactivity.atom_registry import AtomRegistryService
    from pyfect.schema import Codec


@dataclass(frozen=True, slots=True)
class SerializableInfo:
    """How a serializable atom's value is written: as JSON under ``key``."""

    key: str
    encode: Callable[[Any], object]
    decode: Callable[[object], Any]
    skip_initial_run: bool = False


def serializable[T: Atom[Any]](
    atom: T, *, key: str, schema: Codec[Any, Any, Never, Never], skip_initial_run: bool = False
) -> T:
    from pyfect.reactivity.atom._combinators import label_site
    from pyfect.schema import decode_sync, encode_sync, to_codec_json

    codec = cast("Codec[Any, Any, Never, Never]", to_codec_json(schema))
    info = SerializableInfo(key, encode_sync(codec), decode_sync(codec), skip_initial_run)
    label = atom.label if atom.label is not None else (key, label_site(3))
    return atom._with(serializable_info=info, label=label)  # pyright: ignore[reportPrivateUsage]


def is_serializable(atom: Atom[Any]) -> bool:
    return atom.serializable_info is not None


def _initial_waiting(_get: Callable[[Atom[Any]], Any]) -> Any:
    return async_result.initial(waiting=True)


def with_server_value_initial[T: Atom[Any]](atom: T) -> T:
    """``with_server_value`` of a waiting ``Initial``."""
    return atom._with(server_value=_initial_waiting)  # pyright: ignore[reportPrivateUsage]


def get_server_value[A](atom: Atom[A], registry: AtomRegistryService) -> A:
    """The atom's server value if it has one, else its value."""
    if atom.server_value is not None:
        return cast("A", atom.server_value(registry.get))
    return registry.get(atom)


__all__ = [
    "SerializableInfo",
    "get_server_value",
    "is_serializable",
    "serializable",
    "with_server_value_initial",
]
