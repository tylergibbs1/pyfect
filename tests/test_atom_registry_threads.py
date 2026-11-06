"""A registry runs on one scheduler and its nodes are not locked, so using it
from another thread while that scheduler runs fails at once with
``RegistryThreadError`` (DOGFOOD pulse #4: ``hydration.dehydrate`` inside
``fx.blocking`` raised ``dictionary changed size during iteration`` on quit).
Effect has no threads; this is pyfect's own rule."""

from collections.abc import Callable
from typing import Any

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.exit import is_failure
from pyfect.reactivity import async_result, atom, atom_registry, hydration
from pyfect.reactivity.atom_registry import AtomRegistryService, RegistryThreadError

_counter = atom.make(0)
_count = atom.make(fx.succeed(1)).serializable(
    key="count", schema=async_result.Schema(success=S.Int)
)

# Every public method of the registry, called as another thread would.
_ENTRY_POINTS: dict[str, Callable[[AtomRegistryService], object]] = {
    "check_thread": lambda r: r.check_thread(),
    "get_nodes": lambda r: r.get_nodes(),
    "get": lambda r: r.get(_counter),
    "set": lambda r: r.set(_counter, 1),
    "set_serializable": lambda r: r.set_serializable("count", None),
    "modify": lambda r: r.modify(_counter, lambda n: (n, n + 1)),
    "update": lambda r: r.update(_counter, lambda n: n + 1),
    "refresh": lambda r: r.refresh(_counter),
    "subscribe": lambda r: r.subscribe(_counter, lambda _: None),
    "mount": lambda r: r.mount(_counter),
    "ensure_node": lambda r: r.ensure_node(_counter),
    "create_node": lambda r: r.ensure_node(_counter),
    "invalidate_atom": lambda r: r.invalidate_atom(_counter),
    "reset": lambda r: r.reset(),
    "dispose": lambda r: r.dispose(),
    "fork": lambda r: r.fork(fx.void, fx.Context.empty()),
}

# Called only by the registry's own nodes and scheduled tasks (which run on
# its scheduler), or reading nothing but the atom.
_INTERNAL = {
    "atom_has_ttl",
    "schedule_atom_removal",
    "schedule_node_removal",
    "remove_node",
    "set_node_timeout",
    "remove_node_timeout",
    "sweep_bucket",
    "remove_idle_node",
    "destroy_node",
}


def _off_thread(thunk: Callable[[], object]) -> fx.Effect[object]:
    """The defect of running ``thunk`` on a blocking thread, if any."""
    return (
        fx.blocking(thunk)
        .exit()
        .map(lambda ex: ex.cause.defects[0] if is_failure(ex) and ex.cause.defects else None)
    )


def test_every_public_method_is_an_entry_point_or_internal() -> None:
    public = {
        name
        for name in dir(AtomRegistryService)
        if not name.startswith("_") and callable(getattr(AtomRegistryService, name))
    }
    assert public == set(_ENTRY_POINTS) | _INTERNAL


@pytest.mark.parametrize("name", sorted(_ENTRY_POINTS))
@testing.live
def test_an_entry_point_called_off_the_scheduler_thread_fails_at_once(name: str):
    registry = atom_registry.make()
    yield from fx.add_finalizer(lambda _: fx.sync(registry.dispose))
    registry.mount(_counter)
    use = _ENTRY_POINTS[name]
    defect = yield from _off_thread(lambda: use(registry))
    assert isinstance(defect, RegistryThreadError)
    assert "(fx.sync, not fx.blocking)" in str(defect)
    assert registry.get(_counter) == 0


@testing.live
def test_dehydrate_inside_blocking_names_the_thread_rule():
    registry = atom_registry.make()
    yield from fx.add_finalizer(lambda _: fx.sync(registry.dispose))
    registry.mount(_count)
    yield from atom_registry.get_result(registry, _count)
    defect = yield from _off_thread(lambda: hydration.dehydrate(registry))
    assert isinstance(defect, RegistryThreadError)
    assert "while its scheduler runs on thread" in str(defect)
    [entry] = yield from fx.sync(lambda: hydration.dehydrate(registry))
    assert entry.key == "count"


def test_a_registry_whose_scheduler_is_not_running_can_be_read_from_any_thread() -> None:
    """Nothing races once the run is over: reading the values left is fine."""
    registries: list[AtomRegistryService] = []

    @fx.gen
    def build():
        registry = atom_registry.make()
        registries.append(registry)
        registry.mount(_counter)
        registry.set(_counter, 3)
        yield from fx.void

    fx.run_blocking(build)
    [registry] = registries
    seen: list[Any] = []
    fx.run_blocking(fx.blocking(lambda: seen.append(registry.get(_counter))))
    assert seen == [3]
