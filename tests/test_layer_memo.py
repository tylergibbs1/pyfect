"""Layer memoization across fresh and nested provides; merged layers'
release."""

import pyfect as fx
from pyfect import layer
from pyfect.context import TagLike
from pyfect.scope import CloseableScope


class S1(fx.Tag[str]): ...


class S2(fx.Tag[str]): ...


class S3(fx.Tag[str]): ...


class Num(fx.Tag[int]): ...


def make_layer[T](tag: TagLike[str, T], n: int, log: list[str]) -> layer.Layer[T]:
    acquire = fx.acquire_release(
        fx.sync(lambda: log.append(f"acquire{n}") or f"s{n}"),
        lambda _a, _e: fx.sync(lambda: log.append(f"release{n}")),
    )
    return layer.effect(tag, acquire)


def make_layer1(log: list[str]) -> layer.Layer[S1]:
    return make_layer(S1, 1, log)


def test_fresh_with_merge():
    """Layer.test.ts: fresh with merge."""
    log: list[str] = []
    l1 = make_layer1(log)
    fx.run_sync(fx.void.pipe(fx.provide(layer.merge(l1, layer.fresh(l1)))))
    assert log == ["acquire1", "acquire1", "release1", "release1"]


def test_fresh_builds_its_whole_subgraph_anew():
    """Layer.test.ts: with multiple layers."""
    log: list[str] = []
    l1 = make_layer1(log)
    env = layer.merge(layer.merge(l1, l1), layer.fresh(layer.merge(l1, l1)))
    fx.run_sync(fx.void.pipe(fx.provide(env)))
    assert log == ["acquire1", "acquire1", "release1", "release1"]


def test_fresh_with_provide():
    """Layer.test.ts: fresh with provide."""
    log: list[str] = []
    l1 = make_layer1(log)
    fx.run_sync(fx.void.pipe(fx.provide(layer.fresh(l1).pipe(fx.provide(l1)))))
    assert log == ["acquire1", "acquire1", "release1", "release1"]


def test_identical_fresh_layers():
    """Layer.test.ts: with identical fresh layers."""
    log: list[str] = []
    l1, l2, l3 = make_layer(S1, 1, log), make_layer(S2, 2, log), make_layer(S3, 3, log)
    env = layer.merge(l2, layer.fresh(l3.pipe(fx.provide(l1)))).pipe(fx.provide(layer.fresh(l1)))
    fx.run_sync(fx.void.pipe(fx.provide(env)))
    assert log == [
        "acquire1",
        "acquire2",
        "acquire1",
        "acquire3",
        "release3",
        "release1",
        "release2",
        "release1",
    ]


def test_nested_provide_reuses_the_outer_build():
    log: list[str] = []
    l1 = make_layer1(log)
    inner = S1().pipe(fx.provide(l1))
    assert fx.run_sync(S1().and_then(inner).pipe(fx.provide(l1))) == "s1"
    assert log == ["acquire1", "release1"]


def test_subsequent_provides_share_the_memo_map():
    """Effect.test.ts: subsequent calls share MemoMap."""
    builds: list[int] = []
    base = layer.sync(Num, lambda: builds.append(1) or 42)
    program: fx.Effect[None] = (
        fx.void.pipe(fx.provide(base, local=True)).pipe(fx.provide(base)).pipe(fx.provide(base))
    )
    fx.run_sync(program)
    assert len(builds) == 2


def test_a_local_provide_always_builds():
    builds: list[int] = []
    base = layer.sync(Num, lambda: builds.append(1) or 42)
    fx.run_sync(Num().pipe(fx.provide(base, local=True)).pipe(fx.provide(base)))
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
            return gate.wait().timeout(1.0).result().map(lambda r: log.append(repr(r)))

        second = layer.effect(S2, fx.acquire_release(fx.succeed("b"), release_second))
        yield from fx.void.pipe(fx.provide(layer.merge(first, second)))

    fx.run_sync(program)
    assert log == ["Ok(value=None)"]


def test_a_provide_inside_a_layer_reuses_what_the_build_already_built():
    """Layer.ts buildWithMemoMap provides CurrentMemoMap while the layer
    builds, so a provide inside a layer's make reuses layers built before it."""
    log: list[str] = []
    l1 = make_layer1(log)
    uses_s1 = layer.effect(S2, S1().pipe(fx.provide(l1)))
    fx.run_sync(S2().pipe(fx.provide(uses_s1.pipe(layer.provide_merge(l1)))))
    assert log == ["acquire1", "release1"]


def test_layer_build_reuses_the_enclosing_provide():
    """Layer.ts buildWithScope forks the ambient CurrentMemoMap."""
    log: list[str] = []
    l1 = make_layer1(log)

    @fx.gen
    def program():
        scope = CloseableScope()
        built = yield from l1.build(scope)
        yield from scope.close(fx.Success(None))
        return built.lookup(S1)[1]

    assert fx.run_sync(program.pipe(fx.provide(l1))) == "s1"
    assert log == ["acquire1", "release1"]


def test_sibling_nested_provides_build_their_own_layers():
    """Layer.ts CurrentMemoMap.forkOrCreate: a nested provide writes into a
    child map, so a later sibling does not reuse a layer its sibling has
    already released."""
    log: list[str] = []
    l1, l2 = make_layer1(log), make_layer(S2, 2, log)
    inner = S2().pipe(fx.provide(l2))
    program = S1().and_then(inner).and_then(inner).pipe(fx.provide(l1))
    assert fx.run_sync(program) == "s2"
    assert log == ["acquire1", "acquire2", "release2", "acquire2", "release2", "release1"]
