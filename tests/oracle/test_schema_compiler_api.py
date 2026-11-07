"""Ports of Effect's ``SchemaCompilerApi.test.ts``.

Python mappings: ``globalThis.Function`` is ``builtins.exec`` (what the JIT
compiler compiles generated source with); a getter on an installed decoder
is a property; ``vi.spyOn(ast, "getParser")`` counts the interpreters the
registry makes for the AST; ``Schema.ReadonlySet`` is ``S.Option`` (a
declaration parsing its type parameter directly; a set cannot hold the
struct's dict outputs); a getter property on the input is a
``Getters`` mapping.
"""

from __future__ import annotations

import builtins
from typing import Any

import pytest

import pyfect.schema as S
from pyfect.exit import Success
from pyfect.option import Some
from pyfect.schema import compiler as SC
from pyfect.schema import jit_compiler
from pyfect.schema.compiler import _registry, runtime

from ._schema_binary import Opt, struct
from ._schema_compiler import Getters, fresh_registry

__all__ = ["fresh_registry"]


def ok(input: object, _options: object = None) -> Any:
    return Success(input)


def field_ast(schema: Any, index: int) -> Any:
    """The node of the struct's ``index``th field."""
    return schema.ast.properties[index].type


def test_resolves_a_type_guard_on_first_invocation():
    """resolves a type guard on first invocation"""
    schema = S.String.annotate(title="lazy type guard")
    ast = schema.ast.to_type()
    guard = S.is_(schema)
    calls = 0

    def is_(_input: object, _options: object) -> bool:
        nonlocal calls
        calls += 1
        return True

    SC.set(ast, SC.CompiledDecoder(is_=is_, decode_effect=ok))
    assert guard(1) is True
    assert guard(2) is True
    assert calls == 2

    SC.set(ast, SC.CompiledDecoder(is_=lambda _i, _o: False, decode_effect=ok))
    assert guard(3) is True
    assert S.is_(schema)(3) is False
    assert calls == 3


def test_reuses_interpreted_candidates_inside_a_selectively_compiled_union(
    monkeypatch: pytest.MonkeyPatch,
):
    """reuses interpreted candidates inside a selectively compiled Union"""
    child = S.String.annotate(title="interpreted Union candidate")
    schema = S.Union(child, S.Number)
    made: list[object] = []
    interpreter = _registry.interpreter

    def counting(ast: Any, resolve: Any, detailed: bool = False) -> Any:
        if ast is child.ast:
            made.append(ast)
        return interpreter(ast, resolve, detailed)

    monkeypatch.setattr(_registry, "interpreter", counting)
    monkeypatch.setattr(runtime, "interpreter", counting)
    jit_compiler.enable(schema.ast)
    make = S.make(schema)
    assert make("first") == "first"
    assert make("second") == "second"
    assert len(made) == 1


def test_retains_a_resolved_union_member_parser_after_replacement():
    """retains a resolved Union member parser after replacement"""
    child = S.String.annotate(title="resolved Union candidate")
    decode = S.decode_unknown_sync(S.Union(child, S.Number))
    assert decode("original") == "original"

    SC.set(
        child.ast,
        SC.CompiledDecoder(
            decode=lambda _i, _o: "replacement", decode_effect=lambda _i, _o: Success("replacement")
        ),
    )
    assert decode("cached") == "cached"
    assert S.decode_unknown_sync(child)("new consumer") == "replacement"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "with nothing installed, AST.parse records no visits, so a parser first run then "
        "keeps every child interpreted, reached or not; Effect resolves an unreached "
        "Union member when first tried"
    ),
)
def test_uses_a_replacement_for_an_unresolved_union_member():
    """uses a replacement for an unresolved Union member"""
    child = S.String.annotate(title="unresolved Union candidate")
    decode = S.decode_unknown_sync(S.Union(S.Number, child))
    assert decode(1) == 1

    SC.set(
        child.ast,
        SC.CompiledDecoder(
            decode=lambda _i, _o: "replacement", decode_effect=lambda _i, _o: Success("replacement")
        ),
    )
    assert decode("first visit") == "replacement"


def test_installs_a_decoder_in_the_shared_registry():
    """installs a decoder in the shared registry"""
    schema = struct(value=S.String)
    early = S.decode_unknown_sync(schema)
    assert early({"value": "interpreted"}) == {"value": "interpreted"}

    decodes = 0

    def decode_effect(_input: object, _options: object) -> Any:
        nonlocal decodes
        decodes += 1
        return Success({"value": "detailed"})

    SC.set(
        schema.ast,
        SC.CompiledDecoder(
            is_=lambda _i, _o: True,
            decode=lambda _i, o: {"value": "compiled"} if o.get("report_input") else SC.INVALID,
            decode_effect=decode_effect,
        ),
    )
    late = S.decode_unknown_sync(schema)
    assert late({"value": 1}, report_input=True) == {"value": "compiled"}
    assert late({"value": 1}) == {"value": "detailed"}
    assert decodes == 1
    # Parsers that resolved the old entry before set keep using it.
    assert early({"value": "interpreted"}) == {"value": "interpreted"}


def test_uses_is_only_for_type_guards():
    """uses is only for type guards"""
    schema = struct(value=S.String)
    validations = 0

    def is_(input: Any, options: object) -> bool:
        assert options is SC.DEFAULT_PARSE_OPTIONS
        return input.get("value") == "accepted"

    def decode(input: object, _options: object) -> object:
        nonlocal validations
        validations += 1
        return input

    SC.set(schema.ast, SC.CompiledDecoder(is_=is_, decode=decode, decode_effect=ok))
    assert S.is_(schema)({"value": "accepted"}) is True
    assert S.is_(schema)({"value": "rejected"}) is False
    assert S.decode_unknown_sync(schema)({"value": "decoded"}) == {"value": "decoded"}
    assert validations == 1


@pytest.mark.parametrize("direction", ["decode", "encode"])
@pytest.mark.parametrize("first_options", [{}, {"report_input": True}])
def test_retains_one_resolved_entry_across_sync_option_paths(
    direction: str, first_options: dict[str, Any]
):
    """retains one resolved entry across sync option paths"""
    _registry.reset()
    schema = struct(value=S.String)

    def make_sync() -> Any:
        if direction == "decode":
            return S.decode_unknown_sync(schema)
        return S.encode_unknown_sync(schema)

    decode = make_sync()
    input = {"value": "original"}
    assert decode(input, **first_options) == input

    SC.set(
        schema.ast,
        SC.CompiledDecoder(
            decode=lambda _i, _o: {"value": "replacement"},
            decode_effect=lambda _i, _o: Success({"value": "replacement"}),
        ),
    )
    assert decode(input) == input
    assert decode(input, report_input=True) == input
    assert make_sync()(input) == {"value": "replacement"}


class _LazyChild:
    def __init__(self) -> None:
        self.reads = 0

    @property
    def decode(self) -> None:
        self.reads += 1

    @property
    def decode_effect(self) -> Any:
        self.reads += 1
        return ok


def test_does_not_resolve_child_operations_until_the_child_is_parsed():
    """does not resolve child operations until the child is parsed"""
    child = S.String.annotate(title="lazy child")
    decoder = _LazyChild()
    SC.set(child.ast, decoder)
    schema = struct(first=S.Number, child=child)
    decode = S.decode_unknown_sync(schema)
    with pytest.raises(S.SchemaError):
        decode({"first": "invalid", "child": "unreached"})
    assert decoder.reads == 0
    assert decode({"first": 1, "child": "reached"}) == {"first": 1, "child": "reached"}
    assert decoder.reads == 2
    assert decode({"first": 2, "child": "cached"}) == {"first": 2, "child": "cached"}
    assert decoder.reads == 2


def test_uses_an_installed_child_decoder_from_an_interpreted_array():
    """uses an installed child decoder from an interpreted Array"""
    child = S.String.annotate(title="installed array child")
    SC.set(
        child.ast,
        SC.CompiledDecoder(
            decode=lambda i, _o: f"{i}!" if isinstance(i, str) else SC.INVALID,
            decode_effect=lambda i, _o: Success(f"{i}!"),
        ),
    )
    assert S.decode_unknown_sync(S.Array(child))(["a"]) == ("a!",)


def test_exposes_the_canonical_missing_value_to_installed_decoders():
    """exposes the canonical missing value to installed decoders"""
    schema = struct(value=Opt(S.String))
    value = field_ast(schema, 0)
    saw_missing = False

    def decode_effect(input: object, _options: object) -> Any:
        nonlocal saw_missing
        saw_missing = input is SC.MISSING
        return Success(input)

    SC.set(
        value,
        SC.CompiledDecoder(
            decode=lambda i, _o: i if isinstance(i, str) else SC.INVALID,
            decode_effect=decode_effect,
        ),
    )
    assert S.decode_unknown_sync(schema)({}) == {}
    assert saw_missing is True


def test_installs_encoders_on_the_flipped_ast():
    """installs encoders on the flipped AST"""
    schema = S.FiniteFromString
    SC.set(
        schema.ast.flip(),
        SC.CompiledDecoder(
            decode=lambda _i, _o: "aot", decode_effect=lambda _i, _o: Success("detailed")
        ),
    )
    assert S.encode_unknown_sync(schema)(1) == "aot"


# ------------------------------------------------------- SchemaJITCompiler


class _CountingExec:
    def __init__(self) -> None:
        self.original = builtins.exec
        self.constructions = 0

    def __call__(self, *args: Any) -> None:
        self.constructions += 1
        self.original(*args)


def test_reuses_option_independent_generated_functions_for_explicit_options(
    monkeypatch: pytest.MonkeyPatch,
):
    """reuses option-independent generated functions for explicit options"""
    schema = struct(nested=struct(value=S.String))
    input = {"nested": {"value": "valid"}}
    counting = _CountingExec()
    monkeypatch.setattr(builtins, "exec", counting)

    jit_compiler.enable(schema.ast)
    decode = S.decode_unknown_sync(schema)
    assert decode(input) == input
    assert S.is_(schema)(input) is True
    initialized = counting.constructions
    assert initialized > 1
    options: list[S.ParseOptions] = [
        {},
        {"report_input": True},
        {"errors": "all"},
        {"disable_checks": True},
    ]
    for option in options:
        assert decode(input, **option) == input
        assert S.is_(schema)(input) is True
        assert counting.constructions == initialized


def test_keeps_generated_operations_lazy(monkeypatch: pytest.MonkeyPatch):
    """keeps generated operations lazy"""
    schema = struct(value=S.String)
    counting = _CountingExec()
    monkeypatch.setattr(builtins, "exec", counting)

    jit_compiler.enable(schema.ast)
    assert counting.constructions == 1
    assert S.decode_unknown_sync(schema)({"value": "valid"}) == {"value": "valid"}
    assert counting.constructions > 1


def test_replaces_only_the_selected_ast_and_leaves_resolved_parsers_intact():
    """replaces only the selected AST and leaves resolved parsers intact"""
    selected = struct(value=S.String)
    untouched = struct(value=S.String)
    early = S.decode_unknown_sync(selected)
    assert early({"value": "valid"}) == {"value": "valid"}

    jit_compiler.enable(selected.ast)

    early_input = Getters({"value": 1})
    with pytest.raises(S.SchemaError):
        early(early_input)
    assert early_input.reads["value"] == 1

    selected_input = Getters({"value": 1})
    with pytest.raises(S.SchemaError):
        S.decode_unknown_sync(selected)(selected_input)
    assert selected_input.reads["value"] == 2

    untouched_input = Getters({"value": 1})
    with pytest.raises(S.SchemaError):
        S.decode_unknown_sync(untouched)(untouched_input)
    assert untouched_input.reads["value"] == 1


def test_compiles_descendants_through_an_unsupported_lazy_root():
    """compiles descendants through an unsupported lazy root"""
    child = struct(value=S.String)
    schema = S.suspend(lambda: child)
    jit_compiler.enable(schema.ast)

    input = Getters({"value": 1})
    with pytest.raises(S.SchemaError):
        S.decode_unknown_sync(schema)(input)
    assert input.reads["value"] == 2


def test_prepares_declaration_type_parameters_with_the_selective_compiler_on_first_use():
    """prepares declaration type parameters with the selective compiler on first use"""
    child = struct(value=S.String)
    schema = S.Option(child)
    jit_compiler.enable(schema.ast)
    decode = S.decode_unknown_sync(schema)
    assert decode(Some({"value": "a", "extra": True})) == Some({"value": "a"})
    with pytest.raises(S.SchemaError):
        decode(Some({"value": 1}))


def test_does_not_initialize_unused_declaration_type_parameter_operations():
    """does not initialize unused declaration type parameter operations"""
    child = struct(value=S.String)
    decoder = _LazyChild()
    SC.set(child.ast, decoder)
    schema = S.Option(child)
    jit_compiler.enable(schema.ast)
    decode = S.decode_unknown_sync(schema)
    assert decoder.reads == 0
    assert decode(None) is None
    assert decoder.reads == 0
    assert decode(Some({"value": "a"})) == Some({"value": "a"})
    assert decoder.reads == 2


def test_preserves_an_installed_decoder_when_dynamic_code_generation_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
):
    """preserves an installed decoder when dynamic code generation is unavailable"""
    schema = struct(value=S.String)
    SC.set(
        schema.ast,
        SC.CompiledDecoder(
            decode=lambda _i, _o: {"value": "installed"},
            decode_effect=lambda _i, _o: Success({"value": "installed"}),
        ),
    )

    def unavailable(*_args: object) -> None:
        raise RuntimeError("dynamic function generation unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "exec", unavailable)
        jit_compiler.enable(schema.ast)

    assert S.decode_unknown_sync(schema)({"value": 1}) == {"value": "installed"}
