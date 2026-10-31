import pyfect as fx
from pyfect.reactivity import atom, atom_registry

# An atom is a recipe for a value; a registry computes it and holds it.
count = atom.make(1)
doubled = atom.make(lambda get: get(count) * 2)


# A family makes one atom per key, so `todo(1)` is the same atom every time.
@atom.family
def todo(id: int) -> atom.Writable[str, str]:
    return atom.make(f"todo {id}")


@fx.gen
def program():
    registry = atom_registry.make()
    yield from fx.add_finalizer(lambda _: fx.sync(registry.dispose))

    print("doubled:", registry.get(doubled))
    cancel = registry.subscribe(doubled, lambda value: print("doubled is now", value))
    registry.set(count, 5)
    registry.update(count, lambda n: n + 1)
    cancel()

    print(todo(1) is todo(1), registry.get(todo(2)))


fx.run_main(fx.scoped(program))
