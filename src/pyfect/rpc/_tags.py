"""The RPC tags a group or entity lists (``RpcGroup[Literal[...]]``), checked
against its RPCs when the class is defined."""

import types
from collections.abc import Mapping
from typing import Literal, Never, TypeVar, Union, cast, get_args, get_origin

from pyfect.rpc._rpc import AnyRpc

# Contravariant, so the bare ``RpcGroup`` (``Never``: no list) is every group.
Tags_contra = TypeVar("Tags_contra", bound=str, contravariant=True, default=Never)


def _listed(arg: object) -> frozenset[str] | None:
    """The tags a ``Literal`` (or a union of them) lists; ``None`` for
    ``Never`` or a type variable (no list)."""
    if arg is Never or isinstance(arg, TypeVar):
        return None
    if get_origin(arg) is Literal:
        tags = get_args(arg)
    elif get_origin(arg) in (Union, types.UnionType):
        return frozenset[str]().union(*(_listed(member) or () for member in get_args(arg)))
    else:
        tags = ()
    if not tags or not all(isinstance(tag, str) for tag in tags):
        raise TypeError(f"list a group's RPC tags as a Literal of strings, not {arg!r}")
    return frozenset(cast("tuple[str, ...]", tags))


def check_listed_tags(cls: type, generic: type, rpcs: Mapping[str, AnyRpc]) -> None:
    """Check the tags ``cls`` lists (``generic[Literal[...]]``, or inherited)
    are its RPCs' tags."""
    listed: frozenset[str] | None = getattr(cls, "_listed_tags", None)
    for base in types.get_original_bases(cls):
        origin = get_origin(base)
        if isinstance(origin, type) and issubclass(origin, generic):
            params: tuple[object, ...] = getattr(origin, "__parameters__", ())
            args = get_args(base)
            if Tags_contra in params and params.index(Tags_contra) < len(args):
                listed = _listed(args[params.index(Tags_contra)])
    setattr(cls, "_listed_tags", listed)  # noqa: B010
    if listed is None or listed == frozenset(rpcs):
        return
    missing = sorted(set(rpcs) - listed)
    extra = sorted(listed - set(rpcs))
    raise TypeError(
        f"{cls.__name__} lists the RPC tags {sorted(listed)}, but has "
        + "; ".join(
            part
            for part in (
                f"RPCs it does not list: {missing}" if missing else "",
                f"no RPC for: {extra}" if extra else "",
            )
            if part
        )
    )
