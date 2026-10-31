"""``Atom``: reactive values (Effect's ``effect/reactivity/Atom``).

An atom is a recipe for a value; an ``AtomRegistry`` computes and holds
it while it is used. ``make(0)`` is a writable atom; ``make(lambda get:
get(a) + 1)`` derives one (rebuilt when ``a`` changes); ``make(effect)``
and ``make(stream)`` hold an ``AsyncResult`` of their progress. ``fn``
makes a function atom run by writing an argument. ``runtime(layer)``
makes atoms whose effects use a layer's services.

Combinators that keep an atom's kind are methods (``atom.keep_alive()``,
``atom.map(f)``, ``atom.with_fallback(other)``).
"""

from pyfect._public import publish
from pyfect.reactivity.atom._combinators import (
    debounce,
    family,
    initial_value,
    make_refresh_on_signal,
    refresh_on_window_focus,
    set_idle_ttl,
    transform,
    window_focus_signal,
    with_fallback,
    with_refresh,
)
from pyfect.reactivity.atom._constructors import make
from pyfect.reactivity.atom._conversions import (
    get,
    get_result,
    modify,
    mount,
    refresh,
    set,
    to_stream,
    to_stream_result,
    update,
)
from pyfect.reactivity.atom._effect import state
from pyfect.reactivity.atom._fn import (
    AtomResultFn,
    Interrupt,
    InterruptSignal,
    PullChunk,
    PullResult,
    Reset,
    ResetSignal,
    fn,
    fn_sync,
    pull,
)
from pyfect.reactivity.atom._kvs import kvs
from pyfect.reactivity.atom._optimistic import optimistic, optimistic_fn
from pyfect.reactivity.atom._runtime import (
    AtomRuntime,
    RuntimeFactory,
    context,
    runtime,
    with_reactivity,
)
from pyfect.reactivity.atom._serializable import (
    SerializableInfo,
    get_server_value,
    is_serializable,
    serializable,
    with_server_value_initial,
)
from pyfect.reactivity.atom._subscription_ref import subscription_ref
from pyfect.reactivity.atom._swr import swr
from pyfect.reactivity.atom._types import (
    Atom,
    AtomContext,
    FnContext,
    Refresh,
    Writable,
    WriteContext,
    is_atom,
    is_writable,
    readable,
    writable,
)
from pyfect.reactivity.atom_registry import batch

__all__ = [
    "Atom",
    "AtomContext",
    "AtomResultFn",
    "AtomRuntime",
    "FnContext",
    "Interrupt",
    "InterruptSignal",
    "PullChunk",
    "PullResult",
    "Refresh",
    "Reset",
    "ResetSignal",
    "RuntimeFactory",
    "SerializableInfo",
    "Writable",
    "WriteContext",
    "batch",
    "context",
    "debounce",
    "family",
    "fn",
    "fn_sync",
    "get",
    "get_result",
    "get_server_value",
    "initial_value",
    "is_atom",
    "is_serializable",
    "is_writable",
    "kvs",
    "make",
    "make_refresh_on_signal",
    "modify",
    "mount",
    "optimistic",
    "optimistic_fn",
    "pull",
    "readable",
    "refresh",
    "refresh_on_window_focus",
    "runtime",
    "serializable",
    "set",
    "set_idle_ttl",
    "state",
    "subscription_ref",
    "swr",
    "to_stream",
    "to_stream_result",
    "transform",
    "update",
    "window_focus_signal",
    "with_fallback",
    "with_reactivity",
    "with_refresh",
    "with_server_value_initial",
    "writable",
]
publish(globals())
