"""Tags, references, provide_service, layers."""

from dataclasses import dataclass, field
from typing import Protocol

import pytest

import pyfect as fx
from pyfect import layer


class Database(Protocol):
    def get(self, key: str) -> str | None: ...


@dataclass
class InMemoryDb:
    rows: dict[str, str] = field(default_factory=dict[str, str])

    def get(self, key: str) -> str | None:
        return self.rows.get(key)


class Primary(fx.Tag[Database]): ...


class Replica(fx.Tag[Database]): ...


class Prefix(fx.Tag[str]): ...


class Verbose(fx.Reference[bool]):
    @classmethod
    def default(cls) -> bool:
        return False


@fx.gen
def read_both():
    primary = yield from Primary()
    replica = yield from Replica()
    return primary.get("k"), replica.get("k")


def test_tags_with_the_same_shape_stay_distinct():
    eff = read_both.pipe(fx.provide_service(Primary, InMemoryDb({"k": "p"}))).pipe(
        fx.provide_service(Replica, InMemoryDb({"k": "r"}))
    )
    assert fx.run_blocking(eff) == ("p", "r")


def test_references_have_defaults_and_can_be_overridden():
    assert fx.run_blocking(Verbose()) is False
    assert fx.run_blocking(Verbose().pipe(fx.provide_service(Verbose, True))) is True


def test_reference_without_default_is_rejected_at_class_creation():
    with pytest.raises(TypeError, match="default"):

        class Broken(fx.Reference[int]):  # pyright: ignore[reportUnusedClass]
            pass


def test_provided_services_are_scoped_to_the_effect():
    inner = Prefix().pipe(fx.provide_service(Prefix, "inner"))

    @fx.gen
    def program():
        a = yield from inner
        b = yield from Prefix()
        return a, b

    assert fx.run_blocking(program.pipe(fx.provide_service(Prefix, "outer"))) == ("inner", "outer")


def test_forked_fibers_see_the_parents_services():
    @fx.gen
    def program():
        fiber = yield from Prefix().fork()
        return (yield from fiber.join())

    assert fx.run_blocking(program.pipe(fx.provide_service(Prefix, "x"))) == "x"


def test_missing_service_is_a_defect_with_a_clear_message():
    eff: fx.Effect[str] = Prefix()  # type: ignore[assignment]  # deliberately lie to the checker
    with pytest.raises(fx.MissingServiceError, match="Prefix"):
        fx.run_blocking(eff)


# --- layers ---------------------------------------------------------------------


def test_layer_succeed_and_provide():
    live = layer.merge(
        layer.succeed(Primary, InMemoryDb({"k": "p"})),
        layer.succeed(Replica, InMemoryDb({"k": "r"})),
    )
    assert fx.run_blocking(read_both.pipe(fx.provide(live))) == ("p", "r")


def test_partial_provide_leaves_the_rest():
    eff = read_both.pipe(fx.provide(layer.succeed(Primary, InMemoryDb({"k": "p"}))))
    eff2 = eff.pipe(fx.provide(layer.succeed(Replica, InMemoryDb({"k": "r"}))))
    assert fx.run_blocking(eff2) == ("p", "r")


def test_layers_can_depend_on_layers():
    builds: list[str] = []

    @fx.gen
    def make_db():
        prefix = yield from Prefix()
        builds.append("db")
        return InMemoryDb({"k": prefix + "!"})

    db = layer.effect(Primary, make_db)
    prefix = layer.succeed(Prefix, "hello")
    eff = Primary().map(lambda d: d.get("k")).pipe(fx.provide(db.pipe(fx.provide(prefix))))
    assert fx.run_blocking(eff) == "hello!"
    assert builds == ["db"]


def test_a_shared_layer_is_built_once_per_provide():
    builds: list[str] = []
    base = layer.sync(Prefix, lambda: builds.append("built") or "p")

    @fx.fn
    def make(tag_name: str):
        p = yield from Prefix()
        return InMemoryDb({"k": f"{tag_name}:{p}"})

    primary = layer.effect(Primary, make("primary")).pipe(fx.provide(base))
    replica = layer.effect(Replica, make("replica")).pipe(fx.provide(base))
    assert fx.run_blocking(read_both.pipe(fx.provide(layer.merge(primary, replica)))) == (
        "primary:p",
        "replica:p",
    )
    assert builds == ["built"]


def test_fresh_layers_are_not_shared():
    builds: list[str] = []
    base = layer.fresh(layer.sync(Prefix, lambda: builds.append("built") or "p"))
    primary = layer.effect(Primary, Prefix().map(lambda p: InMemoryDb({"k": p}))).pipe(
        fx.provide(base)
    )
    replica = layer.effect(Replica, Prefix().map(lambda p: InMemoryDb({"k": p}))).pipe(
        fx.provide(base)
    )
    fx.run_blocking(read_both.pipe(fx.provide(layer.merge(primary, replica))))
    assert builds == ["built", "built"]


def test_layer_resources_are_released_after_the_program():
    log: list[str] = []

    acquire = fx.acquire_release(
        fx.sync(lambda: log.append("open") or InMemoryDb({"k": "v"})),
        lambda _db, _exit: fx.sync(lambda: log.append("close")),
    )
    live = layer.effect(Primary, acquire)
    program = Primary().map(lambda d: log.append("use") or d.get("k"))
    assert fx.run_blocking(program.pipe(fx.provide(live))) == "v"
    assert log == ["open", "use", "close"]


def test_a_failing_layer_fails_the_program():
    @dataclass
    class ConnectError(fx.TaggedError):
        host: str

    bad = layer.effect(Primary, fx.fail(ConnectError("db.local")))
    ex = fx.run_blocking_exit(Primary().pipe(fx.provide(bad)))
    assert isinstance(ex, fx.Failure) and ex.cause.failures == (ConnectError("db.local"),)


def test_provide_merge_keeps_both_outputs():
    both = layer.effect(Primary, Prefix().map(lambda p: InMemoryDb({"k": p}))).pipe(
        layer.provide_merge(layer.succeed(Prefix, "shared"))
    )

    @fx.gen
    def program():
        db = yield from Primary()
        p = yield from Prefix()
        return db.get("k"), p

    assert fx.run_blocking(program.pipe(fx.provide(both))) == ("shared", "shared")
