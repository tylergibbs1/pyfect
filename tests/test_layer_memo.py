"""Layer memoization across nested provides; merged layers' release.
``fresh`` is covered by the ports in ``tests/oracle/test_layer.py``."""

import pyfect as fx
from pyfect import layer
from pyfect.context import Provides
from pyfect.scope import CloseableScope


class S1(fx.Tag[str]): ...


class S2(fx.Tag[str]): ...


class S3(fx.Tag[str]): ...


class Num(fx.Tag[int]): ...


def make_layer[T](tag: Provides[str, T], n: int, log: list[str]) -> layer.Layer[T]:
    acquire = fx.acquire_release(
        fx.sync(lambda: log.append(f"acquire{n}") or f"s{n}"),
        lambda _a, _e: fx.sync(lambda: log.append(f"release{n}")),
    )
    return layer.effect(tag, acquire)


def make_layer1(log: list[str]) -> layer.Layer[S1]:
    return make_layer(S1, 1, log)


def test_nested_provide_reuses_the_outer_build():
    log: list[str] = []
    l1 = make_layer1(log)
    inner = S1().pipe(fx.provide(l1))
    assert fx.run_blocking(S1().and_then(inner).pipe(fx.provide(l1))) == "s1"
    assert log == ["acquire1", "release1"]


def test_subsequent_provides_share_the_memo_map():
    """Effect.test.ts: subsequent calls share MemoMap."""
    builds: list[int] = []
    base = layer.sync(Num, lambda: builds.append(1) or 42)
    program: fx.Effect[None] = (
        fx.void.pipe(fx.provide(base, local=True)).pipe(fx.provide(base)).pipe(fx.provide(base))
    )
    fx.run_blocking(program)
    assert len(builds) == 2


def test_a_local_provide_always_builds():
    builds: list[int] = []
    base = layer.sync(Num, lambda: builds.append(1) or 42)
    fx.run_blocking(Num().pipe(fx.provide(base, local=True)).pipe(fx.provide(base)))
    assert len(builds) == 2


def test_merged_layers_release_in_parallel():
    """Layer.ts mergeAll builds each layer in a sequential child of a
    parallel scope. S2's release waits for S1's, which a sequential release
    (last registered first) would only start afterwards."""
    log: list[str] = []

    @fx.gen
    def program():
        gate = yield from fx.Deferred[None].make()
        first = layer.effect(
            S1, fx.acquire_release(fx.succeed("a"), lambda _a, _e: gate.succeed(None))
        )

        def release_second(_a: str, _e: object) -> fx.Effect[None]:
            return gate.wait().timeout("1 second").result().map(lambda r: log.append(repr(r)))

        second = layer.effect(S2, fx.acquire_release(fx.succeed("b"), release_second))
        yield from fx.void.pipe(fx.provide(layer.merge(first, second)))

    fx.run_blocking(program)
    assert log == ["Ok(value=None)"]


def test_a_provide_inside_a_layer_reuses_what_the_build_already_built():
    """Layer.ts buildWithMemoMap provides CurrentMemoMap while the layer
    builds, so a provide inside a layer's make reuses layers built before it."""
    log: list[str] = []
    l1 = make_layer1(log)
    uses_s1 = layer.effect(S2, S1().pipe(fx.provide(l1)))
    fx.run_blocking(S2().pipe(fx.provide(uses_s1.pipe(layer.provide_merge(l1)))))
    assert log == ["acquire1", "release1"]


def test_layer_build_reuses_the_enclosing_provide():
    """Layer.ts buildWithScope forks the ambient CurrentMemoMap."""
    log: list[str] = []
    l1 = make_layer1(log)

    @fx.gen
    def program():
        scope = CloseableScope()
        built = yield from l1.build_with_scope(scope)
        yield from scope.close(fx.Success(None))
        return built.get(S1)

    assert fx.run_blocking(program.pipe(fx.provide(l1))) == "s1"
    assert log == ["acquire1", "release1"]


def test_sibling_nested_provides_build_their_own_layers():
    """Layer.ts CurrentMemoMap.forkOrCreate: a nested provide writes into a
    child map, so a later sibling does not reuse a layer its sibling has
    already released."""
    log: list[str] = []
    l1, l2 = make_layer1(log), make_layer(S2, 2, log)
    inner = S2().pipe(fx.provide(l2))
    program = S1().and_then(inner).and_then(inner).pipe(fx.provide(l1))
    assert fx.run_blocking(program) == "s2"
    assert log == ["acquire1", "acquire2", "release2", "acquire2", "release2", "release1"]
