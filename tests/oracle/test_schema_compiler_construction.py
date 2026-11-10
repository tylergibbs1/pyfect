"""Ports of Effect's ``SchemaCompilerConstruction.test.ts`` (with its
``fixtures/construction.ts``).

Python mappings: ``vi.spyOn(Codegen, "generate")`` patches
``pyfect.schema.compiler._codegen.generate``; ``Object.hasOwn(entry, op)``
is ``entry.resolved(op)``; a getter on an installed decoder is a property;
``Schema.ReadonlySet`` is ``S.Option`` (a declaration parsing its type
parameter directly; a set cannot hold the struct's dict outputs);
``undefined`` inputs are ``None``. The fixture's ``class`` case is left out:
a pyfect class's ``make`` takes instances, not plain objects (see
``test_schema_class.py``). ``schema.make`` is a method, so "initializes and
caches makers on first access" checks that bound makers compare equal.

The "keeps the caller" titles are ported but for the stack: a Python exception has a
traceback only once raised, so there is no creation stack to name the caller (the made
error has none, ``__traceback__ is None``). ``Class.make`` takes plain fields here as in
Effect (``C.make({"value": ...})``); its type asks for an instance.
"""

from __future__ import annotations

from typing import Any

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.exit import Failure, Success
from pyfect.option import Some
from pyfect.schema import compiler as SC
from pyfect.schema import jit_compiler
from pyfect.schema.compiler import _codegen, _registry

from ._schema_binary import Opt, struct
from ._schema_compiler import fresh_registry

__all__ = ["fresh_registry"]


def ok(input: object, _options: object = None) -> Any:
    return Success(input)


def field_ast(schema: Any, index: int) -> Any:
    """The node of the struct's ``index``th field."""
    return schema.ast.properties[index].type


# ---------------------------------------------------------------- fixtures

_events: list[str] = []


def _default_value() -> int:
    _events.append("default")
    return 1


def _checked(input: Any) -> bool:
    _events.append("check")
    return input["value"] > 0


_value: Any = S.Number.pipe(S.with_constructor_default(fx.sync(_default_value)))  # pyright: ignore[reportArgumentType]

_CASES: dict[str, tuple[Any, list[object]]] = {
    "struct": (
        struct(value=_value, optional=Opt(S.String)).check(S.make_filter(_checked)),
        [{}, {"value": None}, {"value": -1}, {"value": "bad", "optional": 1}, {"value": 2, "x": 1}],
    ),
    "array": (S.Array(_value), [[None, 2], ["bad", 3], None]),
    "tuple": (
        S.TupleWithRest(S.Tuple(_value), S.String, S.Boolean),
        [[], [None, "a", True], ["bad", 1, False], [1, True]],
    ),
    "optionalTuple": (S.Tuple(S.optional_key(S.Undefined)), [[], [None], [1], [None, 2]]),
    "record": (S.Record(S.String, _value), [{"a": None}, {"a": "bad", "b": "bad"}, {}, None]),
    "mixedRecord": (
        S.StructWithRest(
            struct(value=_value), S.Record(S.TemplateLiteral("x-", S.String), S.Number)
        ),
        [{}, {"value": 1, "x-a": 2}, {"value": "bad", "x-a": "bad", "extra": True}],
    ),
    "union": (
        S.Union(
            struct(_tag=S.tag("A"), value=_value),
            struct(_tag=S.tag("B"), text=S.String),
        ),
        [{}, {"text": "a"}, {"_tag": "A", "value": "bad"}, {"_tag": "C"}],
    ),
    "oneOf": (S.Union(S.String, S.Literal("a"), mode="one_of"), ["a", "b", 1]),
    "transformed": (
        struct(value=S.FiniteFromString.pipe(S.with_constructor_default(fx.succeed(1.0)))),
        [{}, {"value": "1"}, {"value": 2}],
    ),
    "declaration": (S.Option(S.Number), [Some(1), Some("bad"), 1]),
    "empty": (struct(), [{}, 1, [], None]),
}

_OPTIONS: list[S.ParseOptions] = [
    {},
    {"errors": "all", "report_input": True},
    {"on_excess_property": "error"},
    {"disable_checks": True},
]


# ------------------------------------------------------------------- tests


class _C(S.Class):
    value: str


class _E(S.TaggedError, tag="E"):
    message: str


def _fields(**values: object) -> Any:
    """Plain fields for ``Class.make``, typed as the instance it asks for."""
    return values


def test_uses_an_installed_constructor_for_class_make_without_reinitializing_it():
    """uses an installed constructor for Class.make without reinitializing it"""
    instance = _C(value="installed")
    reads = 0

    class Installed:
        decode_effect = staticmethod(ok)

        @property
        def make_effect(self) -> Any:
            nonlocal reads
            reads += 1

            def make(_input: object, _options: object) -> Any:
                return Success(instance)

            return make

    SC.set(_C.ast.to_type(), Installed())
    assert _C.make(_fields(value="input")) is instance
    assert _C.make(_fields(value="another input")) is instance
    assert reads == 1


def test_uses_an_installed_synchronous_constructor_for_class_make_without_resolving_make_effect():
    """uses an installed synchronous constructor for Class.make without resolving makeEffect"""
    instance = _C(value="installed")

    class Installed:
        decode_effect = staticmethod(ok)

        @staticmethod
        def make(_input: object, _options: object) -> Any:
            return instance

        @property
        def make_effect(self) -> Any:
            raise RuntimeError("unused detailed constructor")

    SC.set(_C.ast.to_type(), Installed())
    assert _C.make(_fields(value="input")) is instance


def test_constructs_and_validates_class_fields_with_selective_compilation():
    """constructs and validates class fields with selective compilation"""
    jit_compiler.enable(_C.ast.to_type())
    assert _C.make(_fields(value="input")) == _C(value="input")
    with pytest.raises(S.SchemaError):
        _C.make(_fields(value=1))


def _made_at_callsite() -> _E:
    return _E.make(_fields(message="failure"))


def test_keeps_the_caller_and_honors_a_custom_child_constructor_for_an_interpreted_class():
    """keeps the caller and honors a custom child constructor for an interpreted class"""

    class Custom:
        decode_effect = staticmethod(ok)

        @staticmethod
        def make_effect(_input: object, _options: object) -> Any:
            return Success({"_tag": "E", "message": "custom child constructor"})

    _registry.set(_E.ast.to_type(), None, lambda child: _registry.set(child, Custom()))
    error = _made_at_callsite()
    assert error.__traceback__ is None
    assert error.message == "custom child constructor"


@pytest.mark.parametrize("registration", ["decoder", "compiler"])
@testing.effect
def test_keeps_the_caller_with_a_registration_that_has_no_constructor_operations(
    registration: str,
):
    """keeps the caller with a ${registration} that has no constructor operations"""
    reads = 0

    class NoConstructor:
        decode_effect = staticmethod(ok)

        @property
        def make_effect(self) -> Any:
            nonlocal reads
            reads += 1

    decoder = NoConstructor()
    ast = _E.ast.to_type()
    if registration == "decoder":
        SC.set(ast, decoder)
    else:
        _registry.set_compiler(
            ast, lambda _ast, _resolve, operation: getattr(decoder, operation, None)
        )
    assert reads == 0
    assert _made_at_callsite().__traceback__ is None
    assert _made_at_callsite().message == "failure"
    made = yield from _E.make_effect(_fields(message="failure"))
    assert made.message == "failure"
    assert reads == 1


@testing.effect
def test_initializes_and_caches_makers_on_first_access():
    """initializes and caches makers on first access"""
    schema = struct(value=S.NumberFromString)
    make, make_effect, make_option = schema.make, schema.make_effect, schema.make_option
    assert schema.make == make
    assert schema.make_effect == make_effect
    assert schema.make_option == make_option
    assert make({"value": 0}) == {"value": 0}
    assert (yield from make_effect({"value": 1})) == {"value": 1}
    assert make_option({"value": 2}) == Some({"value": 2})


@testing.effect
def test_matches_interpreted_construction_effects_and_options():
    """matches interpreted construction, effects and options"""

    def snapshot(schema: Any, inputs: list[object]) -> fx.Effect[list[object]]:
        def run() -> Any:
            out: list[object] = []
            make = S.make_effect(schema)
            for options in _OPTIONS:
                for input in inputs:
                    _events.clear()
                    result = yield from make(input, **options).result()
                    out.append((result, list(_events)))
            return out

        return fx.gen(run)

    # Capture every interpreted result before installing shared child ASTs.
    interpreted: list[list[object]] = []
    for schema, inputs in _CASES.values():
        interpreted.append((yield from snapshot(schema, inputs)))
    for index, (name, (schema, inputs)) in enumerate(_CASES.items()):
        jit_compiler.enable(schema.ast.to_type())
        assert (yield from snapshot(schema, inputs)) == interpreted[index], name


def test_keeps_selective_compilation_below_an_interpreted_suspend():
    """keeps selective compilation below an interpreted Suspend"""
    forced = 0
    child = struct(value=S.String)

    def thunk() -> Any:
        nonlocal forced
        forced += 1
        return child

    schema = S.suspend(thunk)
    jit_compiler.enable(schema.ast.to_type())
    assert forced == 0
    assert S.make(schema)({"value": "a"}) == {"value": "a"}
    assert forced == 1


def _spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, str]]:
    calls: list[tuple[object, str]] = []
    generate = _codegen.generate

    def spy(ast: Any, operation: Any) -> str | None:
        calls.append((ast, operation))
        return generate(ast, operation)

    monkeypatch.setattr(_codegen, "generate", spy)
    return calls


def _count(calls: list[tuple[object, str]], *operations: str) -> int:
    return sum(1 for _, operation in calls if operation in operations)


def test_compiles_only_the_raw_constructor_when_construction_succeeds(
    monkeypatch: pytest.MonkeyPatch,
):
    """compiles only the raw constructor when construction succeeds"""
    schema = struct(a=S.String)
    calls = _spy(monkeypatch)
    jit_compiler.enable(schema.ast)
    assert S.make(schema)({"a": "a"}) == {"a": "a"}
    assert _count(calls, "decode", "is") == 0
    assert _count(calls, "make") == 1
    assert _count(calls, "make_effect") == 0


def test_does_not_compile_construction_when_only_decoding_is_used(
    monkeypatch: pytest.MonkeyPatch,
):
    """does not compile construction when only decoding is used"""
    schema = struct(a=S.String)
    calls = _spy(monkeypatch)
    jit_compiler.enable(schema.ast)
    assert S.decode_unknown_sync(schema)({"a": "a"}) == {"a": "a"}
    assert _count(calls, "make_effect") == 0
    assert S.make(schema)({"a": "a"}) == {"a": "a"}
    assert _count(calls, "make") == 1
    assert _count(calls, "make_effect") == 0


class _LazyMake:
    def __init__(self) -> None:
        self.reads = 0

    @property
    def decode_effect(self) -> Any:
        return ok

    @property
    def make_effect(self) -> Any:
        self.reads += 1
        return ok


@pytest.mark.parametrize("compiled", [False, True])
def test_initializes_only_reached_constructor_children(compiled: bool):
    """initializes only reached constructor children, compiled=${compiled}"""
    child = S.String.annotate(title="lazy constructor child")
    decoder = _LazyMake()
    SC.set(child.ast, decoder)
    schema = struct(first=S.Number, child=child)
    if compiled:
        jit_compiler.enable(schema.ast)
    make = S.make(schema)
    with pytest.raises(S.SchemaError):
        make({"first": "invalid", "child": "unreached"})
    assert decoder.reads == 0
    assert make({"first": 1, "child": "a"}) == {"first": 1, "child": "a"}
    assert make({"first": 2, "child": "b"}) == {"first": 2, "child": "b"}
    assert decoder.reads == 1


def test_prepares_selective_declaration_parameters_for_public_decoders_in_the_callback():
    """prepares selective Declaration parameters for public decoders in the callback"""
    child = struct(value=S.String)
    schema = S.Option(child)
    jit_compiler.enable(schema.ast.to_type())
    assert S.make(schema)(Some({"value": "a"})) == Some({"value": "a"})
    assert _registry.resolve(child.ast).compiled is not None


def test_does_not_restart_a_parent_if_compilation_fails_after_a_default(
    monkeypatch: pytest.MonkeyPatch,
):
    """does not restart a parent if compilation fails after a default"""
    defaults = 0
    child = struct(value=S.String)

    def default() -> dict[str, str]:
        nonlocal defaults
        defaults += 1
        return {"value": "default"}

    schema = struct(child=child.pipe(S.with_constructor_default(fx.sync(default))))
    child_ast = field_ast(schema, 0)
    generate = _codegen.generate

    def failing(ast: Any, operation: Any) -> str | None:
        if ast is child_ast and operation == "make_effect":
            assert defaults == 1
            raise RuntimeError("child compile failed")
        return generate(ast, operation)

    monkeypatch.setattr(_codegen, "generate", failing)
    jit_compiler.enable(schema.ast)
    assert S.make(schema)({}) == {"child": {"value": "default"}}
    assert defaults == 1


@pytest.mark.parametrize("operation", ["make", "decode"])
def test_keeps_the_other_operation_compiled_after_compilation_fails(
    operation: str, monkeypatch: pytest.MonkeyPatch
):
    """keeps the other operation compiled after ${operation} compilation fails"""
    schema = struct(a=S.String)
    jit_compiler.enable(schema.ast)
    generate = _codegen.generate
    calls: list[tuple[object, str]] = []

    def failing(ast: Any, key: Any) -> str | None:
        calls.append((ast, key))
        if ast is schema.ast and key == operation:
            raise RuntimeError("compile failed")
        return generate(ast, key)

    monkeypatch.setattr(_codegen, "generate", failing)
    first: Any = S.make(schema) if operation == "make" else S.decode_unknown_sync(schema)
    assert first({"a": "a"}) == {"a": "a"}
    second: Any = S.decode_unknown_sync(schema) if operation == "make" else S.make(schema)
    assert second({"a": "a"}) == {"a": "a"}
    other = "decode" if operation == "make" else "make"
    assert any(ast is schema.ast and key == other for ast, key in calls)


class _OnlyMakeEffect:
    def __init__(self) -> None:
        self.reads = 0
        self.calls = 0

    @property
    def decode_effect(self) -> Any:
        raise RuntimeError("unused decoder")

    @property
    def decode(self) -> Any:
        raise RuntimeError("unused fast decoder")

    @property
    def is_(self) -> Any:
        raise RuntimeError("unused guard")

    @property
    def make_effect(self) -> Any:
        self.reads += 1

        def make(input: object, _options: object) -> Any:
            self.calls += 1
            return fx.succeed(input)

        return make


def test_resolves_installed_construction_lazily_and_independently_from_decoding():
    """resolves installed construction lazily and independently from decoding"""
    schema = struct(a=S.String)
    decoder = _OnlyMakeEffect()
    SC.set(schema.ast, decoder)
    make = S.make(schema)
    assert decoder.reads == 0
    assert make({"a": "a"}) == {"a": "a"}
    assert S.make(schema)({"a": "b"}) == {"a": "b"}
    assert decoder.reads == 1
    assert decoder.calls == 2


class _SyncMake:
    def __init__(self) -> None:
        self.calls = 0

    decode_effect = staticmethod(ok)

    def make(self, input: Any, options: object) -> object:
        self.calls += 1
        assert options is SC.DEFAULT_PARSE_OPTIONS
        return {"a": f"{input['a']}!"}

    @property
    def make_effect(self) -> Any:
        raise RuntimeError("unused detailed constructor")


def test_uses_an_installed_synchronous_constructor_without_resolving_make_effect():
    """uses an installed synchronous constructor without resolving makeEffect"""
    schema = struct(a=S.String)
    decoder = _SyncMake()
    SC.set(schema.ast, decoder)
    assert S.make(schema)({"a": "a"}) == {"a": "a!"}
    assert decoder.calls == 1


def test_falls_back_to_make_effect_after_an_installed_synchronous_constructor_fails():
    """falls back to makeEffect after an installed synchronous constructor fails"""
    schema = struct(a=S.String)
    counts = {"fast": 0, "detailed": 0}

    def make(_input: object, _options: object) -> object:
        counts["fast"] += 1
        return SC.INVALID

    def make_effect(input: object, _options: object) -> Any:
        counts["detailed"] += 1
        return fx.succeed(input)

    SC.set(schema.ast, SC.CompiledDecoder(decode_effect=ok, make=make, make_effect=make_effect))
    assert S.make(schema)({"a": "a"}) == {"a": "a"}
    assert counts == {"fast": 1, "detailed": 1}


def test_does_not_return_a_missing_result_from_an_installed_synchronous_constructor():
    """does not return a missing result from an installed synchronous constructor"""
    schema = struct(a=S.String)
    SC.set(
        schema.ast,
        SC.CompiledDecoder(
            decode_effect=ok,
            make=lambda _i, _o: SC.MISSING,
            make_effect=lambda _i, _o: Success(SC.MISSING),
        ),
    )
    with pytest.raises(S.SchemaError):
        S.make(schema)({"a": "a"})


def _exclaim(input: Any, _options: object) -> object:
    return {"a": f"{input['a']}!"}


def test_composes_an_installed_synchronous_child_constructor_in_a_compiled_array():
    """composes an installed synchronous child constructor in a compiled Array"""
    child = struct(a=S.String)

    def unused(_input: object, _options: object) -> Any:
        raise RuntimeError("unused detailed child constructor")

    SC.set(
        child.ast,
        SC.CompiledDecoder(decode_effect=ok, make=_exclaim, make_effect=unused),
    )
    schema = S.Array(child)
    jit_compiler.enable(schema.ast)
    assert S.make(schema)(({"a": "a"}, {"a": "b"})) == ({"a": "a!"}, {"a": "b!"})


def test_composes_a_compiled_synchronous_child_constructor_in_a_compiled_array():
    """composes a compiled synchronous child constructor in a compiled Array"""
    child = struct(a=S.String)
    jit_compiler.enable(child.ast)
    child_entry = _registry.resolve(child.ast)
    schema = S.Array(child)
    jit_compiler.enable(schema.ast)
    assert S.make(schema)(({"a": "a"},)) == ({"a": "a"},)
    assert child_entry.resolved("make")


def test_falls_back_to_detailed_construction_for_an_invalid_compiled_array():
    """falls back to detailed construction for an invalid compiled Array"""
    schema = S.Array(struct(a=S.String))
    jit_compiler.enable(schema.ast)
    make = S.make(schema)
    assert make(({"a": "a"},)) == ({"a": "a"},)
    with pytest.raises(S.SchemaError):
        make(({"a": 1},))


def test_caches_interpreted_construction_when_an_installed_bundle_omits_it():
    """caches interpreted construction when an installed bundle omits it"""
    schema = struct(a=S.Number.pipe(S.with_constructor_default(fx.succeed(1.0))))

    def not_a_constructor(_input: object, _options: object) -> Any:
        raise RuntimeError("not a constructor")

    SC.set(schema.ast, SC.CompiledDecoder(decode_effect=not_a_constructor))
    entry = _registry.resolve(schema.ast)
    make = entry.make_effect
    assert entry.make_effect is make
    assert S.make(schema)({}) == {"a": 1}


def test_keeps_previously_captured_constructors_after_whole_entry_replacement():
    """keeps previously captured constructors after whole-entry replacement"""
    schema = struct(a=S.String)
    make = S.make(schema)
    assert make({"a": "a"}) == {"a": "a"}
    SC.set(
        schema.ast,
        SC.CompiledDecoder(
            decode_effect=ok, make_effect=lambda _i, _o: Success({"a": "installed"})
        ),
    )
    assert make({"a": "a"}) == {"a": "a"}
    assert S.make(schema)({"a": "a"}) == {"a": "installed"}
    SC.set(schema.ast, SC.CompiledDecoder(decode_effect=ok))
    assert S.make(schema)({"a": "a"}) == {"a": "a"}


def test_uses_type_side_identity_without_applying_root_defaults():
    """uses type-side identity without applying root defaults"""
    schema = S.FiniteFromString.pipe(S.with_constructor_default(fx.succeed(1.0)))
    ast = schema.ast.to_type()
    SC.set(ast, SC.CompiledDecoder(decode_effect=ok, make_effect=ok))
    assert S.make(schema)(2.0) == 2.0
    number = S.Number.pipe(S.with_constructor_default(fx.succeed(1.0)))
    jit_compiler.enable(number.ast)
    with pytest.raises(S.SchemaError):
        S.make(number)(None)  # pyright: ignore[reportArgumentType]
    assert S.make(struct(number=number))({}) == {"number": 1.0}


def test_preserves_missing_separately_from_undefined_for_installed_children():
    """preserves missing separately from undefined for installed children"""
    child = S.Undefined
    inputs: list[object] = []

    def make_effect(input: object, _options: object) -> Any:
        inputs.append(input)
        return Success(input)

    schema = struct(child=Opt(child))
    child_ast = field_ast(schema, 0)
    SC.set(child_ast, SC.CompiledDecoder(decode_effect=ok, make_effect=make_effect))
    assert S.make(schema)({}) == {}
    assert S.make(schema)({"child": None}) == {"child": None}
    assert inputs == [SC.MISSING, None]


def test_lets_parents_and_public_roots_handle_missing_constructor_outputs():
    """lets parents and public roots handle missing constructor outputs"""
    required = S.String.annotate(title="Required construction output")
    schema = struct(required=required, optional=Opt(required))
    optional_ast = field_ast(schema, 1)
    for ast in (required.ast, optional_ast):
        SC.set(
            ast,
            SC.CompiledDecoder(decode_effect=ok, make_effect=lambda _i, _o: Success(SC.MISSING)),
        )
    jit_compiler.enable(schema.ast)
    with pytest.raises(S.SchemaError):
        S.make(schema)({"required": "a"})
    only_optional = struct(optional=Opt(required))
    SC.set(
        field_ast(only_optional, 0),
        SC.CompiledDecoder(decode_effect=ok, make_effect=lambda _i, _o: Success(SC.MISSING)),
    )
    assert S.make(only_optional)({"optional": "a"}) == {}
    with pytest.raises(S.SchemaError):
        S.make(required)("a")


def test_compiles_construction_only_without_nested_records_unions_or_constructor_defaults():
    """compiles construction only without nested records, unions or constructor defaults"""

    def compiles_make(schema: Any) -> bool:
        return _codegen.generate(schema.ast, "make") is not None

    assert compiles_make(struct(a=struct(b=S.String)))
    assert not compiles_make(struct(a=S.Record(S.String, S.Number)))
    assert not compiles_make(struct(a=S.Union(S.String, S.Number)))
    assert not compiles_make(
        struct(a=struct(b=S.String.pipe(S.with_constructor_default(fx.succeed("b")))))
    )


@testing.effect
def test_executes_async_defaults_once_including_on_later_failure():
    """executes async defaults once, including on later failure"""
    defaults = 0

    def default() -> Any:
        nonlocal defaults
        yield from fx.yield_now()
        defaults += 1
        return "default"

    schema = struct(a=S.String.pipe(S.with_constructor_default(fx.gen(default))), b=S.Number)
    jit_compiler.enable(schema.ast)
    make = S.make_effect(schema)
    assert (yield from make({"b": 1})) == {"a": "default", "b": 1}
    exit = yield from make({"b": "bad"}).exit()
    assert isinstance(exit, Failure)
    assert defaults == 2
