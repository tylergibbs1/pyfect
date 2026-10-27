"""Ports of Effect's ``Context.test.ts``.

Each test's docstring is the Effect test title. ``Context.Service<number>(key)``
is a ``Tag[int]`` subclass, ``mapUnsafe`` is ``unsafe_map`` (keyed by tag
class, not by key string) and ``toJSON`` is ``repr``.

Omitted, with the reason:

- "invalidates the fiber cache only for opted-in keys", "flattens after
  repeated base fall-throughs", "defers flattening a large base until enough
  base hits": they test the overlay map and fiber cache, an optimization
  pyfect's context (a plain dict copied on add) doesn't have.
- "supports the Redactable fallback context": no Redactable module.
- "retains the makeUnsafe input map": ``Context(mapping)`` copies the mapping,
  so mutating it afterwards can't change an immutable context.

The overlay "rebase" tests keep their observable half: values, order and the
parent left unchanged.
"""

import pyfect as fx
from pyfect.context import Tag


class A(fx.Tag[int], key="ContextTest/A"): ...


class B(fx.Tag[int], key="ContextTest/B"): ...


class C(fx.Tag[int], key="ContextTest/C"): ...


def _keys(ctx: fx.Context) -> list[str]:
    return [tag.key for tag in ctx.unsafe_map]


def _entries(ctx: fx.Context) -> list[tuple[str, object]]:
    return [(tag.key, value) for tag, value in ctx.unsafe_map.items()]


def test_keeps_the_source_immutable_across_additions():
    """keeps the source immutable across additions"""
    source = fx.Context.make(A, 1)
    result = source.add(B, 2)
    assert _entries(source) == [(A.key, 1)]
    assert _entries(result) == [(A.key, 1), (B.key, 2)]


def test_removes_a_service_with_add_or_omit():
    """removes a service with addOrOmit"""
    context = fx.Context.make(A, 1).pipe(fx.Context.add_or_omit(A, None))
    assert context.get_option(A) is None


def test_preserves_map_insertion_order_for_replacements_and_appends():
    """preserves Map insertion order for replacements and appends"""

    class Ref(fx.Reference[int], key="ContextTest/OrderRef"):
        @classmethod
        def default(cls) -> int:
            return 0

    context = fx.Context.empty().add(A, 1).add(Ref, 2).add(B, 3).add(A, 4).add(C, 5)
    assert _entries(context) == [(A.key, 4), (Ref.key, 2), (B.key, 3), (C.key, 5)]


def test_distinguishes_an_undefined_service_from_an_absent_service():
    """distinguishes an undefined service from an absent service"""

    class Undefined(fx.Tag[int | None], key="ContextTest/Undefined"): ...

    class Missing(fx.Tag[None], key="ContextTest/Missing"): ...

    class Ref(fx.Reference[str | None], key="ContextTest/UndefinedRef"):
        @classmethod
        def default(cls) -> str | None:
            return "default"

    context = fx.Context.make(Undefined, 1).add(Undefined, None).add(Ref, None)
    assert context.get_option(Undefined) == fx.Some(None)
    assert context.get_option(Missing) is None
    assert context.unsafe_get(Undefined) is None
    assert context.get_or_else(Undefined, lambda: 1) is None
    assert context.get_option(Ref) == fx.Some(None)
    assert _entries(context.pipe(fx.Context.pick(Undefined))) == [(Undefined.key, None)]
    assert _entries(fx.Context(context.unsafe_map).pipe(fx.Context.pick(Missing))) == []
    assert context.get(Ref) is None


def test_bounds_deep_overlay_chains_without_changing_values_or_order():
    """bounds deep overlay chains without changing values or order"""
    keys = [type(f"Deep{i}", (Tag,), {}, key=f"ContextTest/Deep{i}") for i in range(20)]
    context: fx.Context = fx.Context.empty()
    for i, key in enumerate(keys):
        context = context.add(key, i)
    assert len(context.unsafe_map) == 20
    assert _keys(context) == [key.key for key in keys]
    for i, key in enumerate(keys):
        assert context.unsafe_get(key) == i


def test_rebases_a_shadowing_overlay_chain_from_a_cold_or_warm_parent():
    """rebases a shadowing overlay chain from a cold or warm parent"""
    keys = [type(f"Rebase{i}", (Tag,), {}, key=f"ContextTest/Rebase{i}") for i in range(8)]
    base = fx.Context.make(A, 1).add(B, 2)
    flat = fx.Context(base.unsafe_map)
    parent: fx.Context = flat.add(A, 10)
    for i in range(7):
        parent = parent.add(keys[i], i)
    expected = [
        (A.key, 10),
        (B.key, 2),
        *((key.key, i) for i, key in enumerate(keys[:7])),
        (C.key, 3),
    ]
    assert _entries(parent.add(C, 3)) == expected
    parent_entries = _entries(parent)
    assert _entries(parent.add(C, 3)) == expected
    assert _entries(parent) == parent_entries
    assert parent.get_option(C) is None


def test_rebases_a_large_base_without_warming_the_pre_rebase_contexts_flat_cache():
    """rebases a large base without warming the pre-rebase context's flat cache"""
    base_keys = [type(f"Base{i}", (Tag,), {}, key=f"ContextTest/Base{i}") for i in range(50)]
    push_keys = [type(f"Push{i}", (Tag,), {}, key=f"ContextTest/Push{i}") for i in range(9)]
    context = fx.Context({key: i for i, key in enumerate(base_keys)})
    for i, key in enumerate(push_keys):
        context = context.add(key, i)
    assert len(context.unsafe_map) == 59
    for i, key in enumerate(base_keys):
        assert context.unsafe_get(key) == i
    for i, key in enumerate(push_keys):
        assert context.unsafe_get(key) == i


def test_supports_the_readonly_map_surface_through_map_unsafe():
    """supports the ReadonlyMap surface through mapUnsafe"""
    services = fx.Context.make(A, 1).add(B, 2).unsafe_map
    assert len(services) == 2
    assert A in services
    assert services[B] == 2
    assert list(services.keys()) == [A, B]
    assert list(services.values()) == [1, 2]
    assert list(services.items()) == [(A, 1), (B, 2)]


def test_supports_equality_and_json_materialization():
    """supports equality and JSON materialization"""
    left = fx.Context.make(A, 1).add(B, 2)
    right = fx.Context({A: 1, B: 2})
    assert left == right
    assert left != fx.Context.make(A, 2)
    assert repr(left) == "Context({ContextTest/A: 1, ContextTest/B: 2})"


def test_merges_with_right_bias_and_preserves_empty_operand_identity():
    """merges with right bias and preserves empty operand identity"""
    left = fx.Context.make(A, 1).add(B, 2)
    right = fx.Context.make(A, 3).add(C, 4)
    assert fx.Context.empty().merge(left) is left
    assert left.merge(fx.Context.empty()) is left
    assert _entries(left.merge(right)) == [(A.key, 3), (B.key, 2), (C.key, 4)]


def test_pick_and_omit_preserve_services_and_source_ordering():
    """pick and omit preserve services and source ordering"""
    source = fx.Context.make(A, 1).add(B, 2).add(C, 0).add(C, 3)
    assert _entries(source.pipe(fx.Context.pick(C))) == [(C.key, 3)]
    assert _entries(source.pipe(fx.Context.pick())) == []
    assert _entries(source) == [(A.key, 1), (B.key, 2), (C.key, 3)]
    assert _entries(source.pipe(fx.Context.pick(C, A))) == [(A.key, 1), (C.key, 3)]
    assert _entries(source.pipe(fx.Context.omit(B))) == [(A.key, 1), (C.key, 3)]


def test_resolves_reference_defaults_lazily_and_caches_them():
    """resolves reference defaults lazily and caches them"""
    calls = 0

    class Ref(fx.Reference[object], key="ContextTest/LazyRef"):
        @classmethod
        def default(cls) -> object:
            nonlocal calls
            calls += 1
            return object()

    context = fx.Context.empty()
    assert _entries(fx.Context.pick(Ref)(context)) == []
    assert calls == 0
    first = context.get(Ref)
    assert calls == 1
    assert context.get(Ref) is first
    assert calls == 1
