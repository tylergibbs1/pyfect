"""Ports of Effect's ``SchemaJITCompilerFallback.test.ts`` and
``SchemaJITCompilerExcessProperties.test.ts``: every schema AST resolved in
this module is compiled.

Python mappings: ``globalThis.Function`` is ``builtins.exec`` (Effect's
``"return true"`` probe is ``exec("pass", {})``); counting ``getParser``
calls counts the interpreters made for the AST. A JavaScript object's
non-enumerable properties are an instance's attributes that are not its own
(class attributes and properties): a struct reads them by name and never
enumerates them, as Effect reads non-enumerable keys. Symbol keys are
string attribute names, the only keys an instance has.
"""

from __future__ import annotations

import builtins
from collections.abc import Iterator, Mapping
from typing import Any, cast

import pytest

import pyfect.schema as S
from pyfect.exit import Failure
from pyfect.schema import ast
from pyfect.schema import transformation as T
from pyfect.schema.compiler import INVALID, _codegen, _registry, runtime

from ._schema_binary import struct
from ._schema_compiler import Getters, fresh_registry, jit_installed

pytestmark = pytest.mark.usefixtures("jit_installed")

__all__ = ["fresh_registry", "jit_installed"]

_STRICT: S.ParseOptions = {"on_excess_property": "error"}
_real_exec = builtins.exec


def _message(raised: pytest.ExceptionInfo[BaseException]) -> str:
    error = raised.value
    assert isinstance(error, S.SchemaError)
    return error.message


class _Interpreters:
    """Counts the interpreters made per AST (Effect's ``getParser`` spy)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.made: list[ast.AST] = []
        original = _registry.interpreter

        def counting(node: ast.AST, resolve: Any, detailed: bool = False) -> Any:
            self.made.append(node)
            return original(node, resolve, detailed)

        monkeypatch.setattr(_registry, "interpreter", counting)
        monkeypatch.setattr(runtime, "interpreter", counting)

    def of(self, node: ast.AST) -> int:
        return sum(made is node for made in self.made)


@pytest.fixture
def interpreters(monkeypatch: pytest.MonkeyPatch) -> _Interpreters:
    return _Interpreters(monkeypatch)


def _is_probe(source: object) -> bool:
    return source == "pass"


# ------------------------------------------------------------------ fallback


def _recovers(
    monkeypatch: pytest.MonkeyPatch, interpreters: _Interpreters, phase: str, first: str
) -> None:
    schema = struct(value=S.String)
    attempts = 0

    def fake(source: object, namespace: Any = None, *_: object) -> None:
        nonlocal attempts
        if _is_probe(source):
            return _real_exec("pass", {})
        attempts += 1
        if phase == "construction":
            raise SyntaxError("invalid generated source")

        def factory(*_: object) -> Any:
            raise RuntimeError("generated factory failed")

        namespace["factory"] = factory
        return None

    monkeypatch.setattr(builtins, "exec", fake)
    decode = S.decode_unknown_sync(schema)
    is_ = S.is_(schema)
    input = {"value": "valid", "extra": True}
    if first == "is":
        assert is_(input) is True
    assert decode(input) == {"value": "valid"}
    assert is_(input) is True
    assert is_({"value": 1}) is False
    with pytest.raises(S.SchemaError) as raised:
        decode({"value": 1})
    assert _message(raised) == 'Expected string\n  at ["value"]'
    with pytest.raises(S.SchemaError) as raised:
        decode(input, on_excess_property="error")
    assert _message(raised) == 'Expected no excess property\n  at ["extra"]'
    assert S.decode_unknown_sync(schema)(input) == {"value": "valid"}
    assert attempts == 1
    assert interpreters.of(schema.ast) == 1


def test_recovers_construction_failure_during_decode_without_retrying(
    monkeypatch: pytest.MonkeyPatch, interpreters: _Interpreters
):
    """recovers construction failure during decode without retrying"""
    _recovers(monkeypatch, interpreters, "construction", "decode")


def test_recovers_construction_failure_during_is_without_retrying(
    monkeypatch: pytest.MonkeyPatch, interpreters: _Interpreters
):
    """recovers construction failure during is without retrying"""
    _recovers(monkeypatch, interpreters, "construction", "is")


def test_recovers_factory_failure_during_decode_without_retrying(
    monkeypatch: pytest.MonkeyPatch, interpreters: _Interpreters
):
    """recovers factory failure during decode without retrying"""
    _recovers(monkeypatch, interpreters, "factory", "decode")


def test_recovers_factory_failure_during_is_without_retrying(
    monkeypatch: pytest.MonkeyPatch, interpreters: _Interpreters
):
    """recovers factory failure during is without retrying"""
    _recovers(monkeypatch, interpreters, "factory", "is")


def test_recovers_errors_in_generate_without_disabling_other_schemas(
    monkeypatch: pytest.MonkeyPatch, interpreters: _Interpreters
):
    """recovers errors in generate without disabling other schemas"""
    generate = _codegen.generate
    calls = 0
    failed = False

    def failing_once(node: ast.AST, operation: Any) -> str | None:
        nonlocal calls, failed
        calls += 1
        if not failed:
            failed = True
            raise RuntimeError("compiler failed")
        return generate(node, operation)

    monkeypatch.setattr(_codegen, "generate", failing_once)
    schema = struct(value=S.String)
    decode = S.decode_unknown_sync(schema)
    assert decode({"value": "valid"}) == {"value": "valid"}
    assert interpreters.of(schema.ast) == 1
    attempts = calls
    assert decode({"value": "again"}) == {"value": "again"}
    assert calls == attempts

    other = struct(value=S.String)
    assert S.decode_unknown_sync(other)({"value": "compiled"}) == {"value": "compiled"}
    assert interpreters.of(other.ast) == 0


def test_recovers_composed_decoder_generation_without_repeating_transformations(
    monkeypatch: pytest.MonkeyPatch,
):
    """recovers composed decoder generation without repeating transformations"""
    transformations = 0

    def trim(value: str) -> str:
        nonlocal transformations
        transformations += 1
        return value.strip()

    field = S.String.pipe(S.decode_to(S.String, T.transform(decode=trim, encode=str)))
    schema = struct(value=field)
    generate = _codegen.generate
    failures: list[ast.AST] = []

    def failing(node: ast.AST, operation: Any) -> str | None:
        if node is schema.ast:
            failures.append(node)
            raise RuntimeError("composed decoder generation failed")
        return generate(node, operation)

    monkeypatch.setattr(_codegen, "generate", failing)
    decode = S.decode_unknown_sync(schema)
    assert decode({"value": " a "}) == {"value": "a"}
    assert decode({"value": " b "}) == {"value": "b"}
    assert transformations == 2
    assert len(failures) == 1


def test_recovers_decoder_generation_without_replaying_its_encoding_or_middleware(
    monkeypatch: pytest.MonkeyPatch,
):
    """recovers decoder generation without replaying its encoding or middleware"""
    counts = {"transformations": 0, "middleware": 0, "attempts": 0, "at_failure": -1}

    def to_struct(value: str) -> Mapping[str, object]:
        counts["transformations"] += 1
        return {"value": value.strip()}

    def middleware(parse: Any, _options: S.ParseOptions) -> Any:
        counts["middleware"] += 1
        return parse

    schema = S.String.pipe(
        S.decode_to(
            struct(value=S.String.check(S.is_min_length(2))),
            T.transform(decode=to_struct, encode=lambda value: cast("str", value["value"])),
        )
    ).pipe(S.middleware_decoding(middleware))
    generate = _codegen.generate

    def failing(node: ast.AST, operation: Any) -> str | None:
        if node is schema.ast:
            counts["attempts"] += 1
            counts["at_failure"] = counts["transformations"]
            raise RuntimeError("local checkpoint generation failed")
        return generate(node, operation)

    monkeypatch.setattr(_codegen, "generate", failing)
    decode = S.decode_unknown_sync(schema)
    assert decode(" valid ") == {"value": "valid"}
    assert counts["at_failure"] == 0
    assert counts["transformations"] == 1
    assert counts["middleware"] == 1
    with pytest.raises(S.SchemaError):
        decode(" x ")
    assert counts["transformations"] == 2
    assert counts["middleware"] == 2
    assert counts["attempts"] == 1


def test_propagates_errors_from_executing_generated_code_without_interpreting_the_input(
    monkeypatch: pytest.MonkeyPatch, interpreters: _Interpreters
):
    """propagates errors from executing generated code without interpreting the input"""
    schema = struct(value=S.String)
    executions = 0

    def run(*_: object) -> object:
        nonlocal executions
        executions += 1
        raise RuntimeError("generated parser failed")

    def fake(source: object, namespace: Any = None, *_: object) -> None:
        if _is_probe(source):
            return _real_exec("pass", {})

        def factory(*_: object) -> Any:
            return run

        namespace["factory"] = factory
        return None

    monkeypatch.setattr(builtins, "exec", fake)
    result = S.decode_unknown_exit(schema)({"value": "valid"})
    assert isinstance(result, Failure)
    assert result.cause.has_dies
    assert executions == 1
    assert interpreters.of(schema.ast) == 0


# --------------------------------------------------------- excess properties


def _compiled(schema: Any) -> tuple[Any, Any]:
    entry = _registry.resolve(schema.__codec__().ast)
    decode, is_ = entry.decode, entry.is_
    assert decode is not None, "Expected a compiled decoder"
    assert is_ is not None, "Expected a compiled type guard"
    return decode, is_


def _never_read(_: object) -> object:
    raise AssertionError("Non-enumerable excess properties must not be read")


class _Hidden:
    """Non-enumerable properties that must not be read."""

    stack = property(_never_read)
    property_is_enumerable = property(_never_read)
    hidden = property(_never_read)

    def __init__(self, **own: object) -> None:
        self.__dict__.update(own)


def test_ignores_non_enumerable_own_properties_without_fallback_or_getter_access():
    """ignores non-enumerable own properties without fallback or getter access"""
    decode, is_ = _compiled(struct(a=S.String))
    input = _Hidden(a="a")
    assert decode(input, _STRICT) == {"a": "a"}
    assert is_(input, _STRICT) is True


def test_rejects_enumerable_excess_properties():
    """rejects enumerable excess properties"""
    schema = struct(a=S.String)
    decode, is_ = _compiled(schema)
    for key in ["b", object()]:
        input = {"a": "a", key: "b"}
        assert decode(input, _STRICT) is INVALID
        assert is_(input, _STRICT) is False
    with pytest.raises(S.SchemaError) as raised:
        S.decode_unknown_sync(schema, on_excess_property="error")({"a": "a", "b": "b"})
    assert _message(raised) == 'Expected no excess property\n  at ["b"]'


def test_symbol_index_signatures_ignore_non_enumerable_properties_in_decode_and_encode():
    """symbol index signatures ignore non-enumerable properties in decode and encode"""
    input = _Hidden(visible=1)
    expected = {"visible": 1}
    schema = S.Record(S.String, S.Number)
    decode, is_ = _compiled(schema)
    options: list[S.ParseOptions] = [{}, _STRICT]
    for option in options:
        assert decode(input, option) == expected
        assert is_(input, option) is True
        assert decode(_Hidden(visible="invalid"), option) is INVALID
        assert is_(_Hidden(visible="invalid"), option) is False
        assert S.encode_unknown_sync(schema, **option)(input) == expected


class _Declared:
    a: object = 1
    declared: object = "a"


def test_validates_non_enumerable_declared_string_and_symbol_properties():
    """validates non-enumerable declared string and symbol properties"""
    schema = struct(a=S.Number, declared=S.String)
    decode, is_ = _compiled(schema)
    input = _Declared()
    assert decode(input, _STRICT) == {"a": 1, "declared": "a"}
    assert is_(input, _STRICT) is True
    assert S.encode_unknown_sync(schema, on_excess_property="error")(input) == {
        "a": 1,
        "declared": "a",
    }
    for key in ["a", "declared"]:
        invalid = type("Invalid", (_Declared,), {key: None})()
        assert decode(invalid, _STRICT) is INVALID
        assert is_(invalid, _STRICT) is False


def test_handles_fixed_fields_and_multiple_index_signatures():
    """handles fixed fields and multiple index signatures"""
    schema = S.StructWithRest(
        struct(fixed=S.String),
        S.Record(S.TemplateLiteral(["field-", S.Number]), S.Number),
        S.Record(S.TemplateLiteral(["sym-", S.String]), S.Number),
    )
    decode, is_ = _compiled(schema)
    expected = {"fixed": "a", "field-1": 1, "sym-visible": 2}
    input: Any = type("Input", (), {"field-2": "invalid", "sym-hidden": "invalid"})()
    for key, value in expected.items():
        setattr(input, key, value)
    assert decode(input, _STRICT) == expected
    assert is_(input, _STRICT) is True
    assert decode({**expected, "extra": 1}, _STRICT) is INVALID
    assert is_({**expected, "extra": 1}, _STRICT) is False
    assert decode({**expected, "sym-visible": "invalid"}, _STRICT) is INVALID
    assert decode({"fixed": "b", "field-3": 3}, _STRICT) == {"fixed": "b", "field-3": 3}


class _Mutating(Getters):
    """Reading ``fixed`` adds a ``sym-added`` key."""

    def __getitem__(self, key: str) -> object:
        value = super().__getitem__(key)
        if key == "fixed":
            self.entries["sym-added"] = "added after excess checking"
            self.reads["sym-added"] = 0
        return value

    def __iter__(self) -> Iterator[str]:
        return iter(list(self.entries))


def test_reuses_the_strict_key_snapshot_before_reading_declared_getters():
    """reuses the strict key snapshot before reading declared getters"""
    schema = S.StructWithRest(
        struct(fixed=S.Boolean), S.Record(S.TemplateLiteral(["sym-", S.String]), S.Number)
    )
    decode, is_ = _compiled(schema)

    def input() -> _Mutating:
        return _Mutating({"sym-visible": 1, "fixed": True})

    assert decode(input(), _STRICT) == {"fixed": True, "sym-visible": 1}
    assert is_(input(), _STRICT) is True
    # Without strict parsing the keys are listed after ``fixed`` is read, so
    # the added key is seen and rejected.
    assert decode(input(), {}) is INVALID
    assert is_(input(), {}) is False
    _registry.reset()
    assert isinstance(S.decode_unknown_exit(schema)(input()), Failure)
    assert S.decode_unknown_sync(schema)(input(), on_excess_property="error") == {
        "fixed": True,
        "sym-visible": 1,
    }


class _NotFound(S.TaggedError, tag="NotFound"):
    id: float


def test_encodes_tagged_errors_carrying_runtime_internals():
    """encodes tagged errors carrying runtime internals"""
    encode = S.encode_unknown_sync(_NotFound, on_excess_property="error")
    try:
        raise _NotFound(id=1)
    except _NotFound as error:
        assert encode(error) == {"_tag": "NotFound", "id": 1}
