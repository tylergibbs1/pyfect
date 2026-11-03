"""``scripts/gen_openai_schemas.py``: the schemas it writes for snippets of
Effect's ``Generated.ts`` behave as Effect's, a shape it does not know
fails naming the declaration, and the checked-in ``generated`` package is
what the reference checkout gives."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from pyfect import schema as S

ROOT = Path(__file__).resolve().parent.parent


def _script() -> Any:
    spec = importlib.util.spec_from_file_location(
        "gen_openai_schemas", ROOT / "scripts" / "gen_openai_schemas.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up
    spec.loader.exec_module(module)
    return module


gen = _script()

_TYPES_IMPORT = "from pyfect.ai.openai.generated import types as _T\n"


def _load(source: str) -> types.SimpleNamespace:
    """The schemas generated for ``source``, run in fresh namespaces."""
    files = gen.generate(source)
    typed: dict[str, Any] = {}
    exec(compile(files["types.py"], "types.py", "exec"), typed)
    schemas: dict[str, Any] = {"_T": types.SimpleNamespace(**typed)}
    text = files["_schemas_0.py"]
    assert _TYPES_IMPORT in text
    exec(compile(text.replace(_TYPES_IMPORT, ""), "_schemas_0.py", "exec"), schemas)
    return types.SimpleNamespace(**schemas)


_STRUCT = """
export type Options = { readonly "name": string; readonly "max_tokens"?: number }
export const Options = Schema.Struct({
  "name": Schema.String.annotate({ "description": "The name" }),
  "max_tokens": Schema.optionalKey(Schema.Number.check(Schema.isGreaterThanOrEqualTo(1)))
}).annotate({ "identifier": "Options" })
"""


def test_struct_keys_checks_and_annotations():
    generated = _load(_STRUCT)
    decode = S.decode_unknown_sync(generated.Options)
    assert decode({"name": "a"}) == {"name": "a"}
    assert decode({"name": "a", "max_tokens": 2}) == {"name": "a", "max_tokens": 2}
    with pytest.raises(S.SchemaError):
        decode({"name": "a", "max_tokens": 0})
    with pytest.raises(S.SchemaError):
        decode({"max_tokens": 2})
    assert generated.Options.ast.annotations["identifier"] == "Options"


def test_literals():
    generated = _load(
        'export type Kind = "x" | "y"\nexport const Kind = Schema.Literals(["x", "y"])\n'
    )
    assert S.decode_unknown_sync(generated.Kind)("y") == "y"
    with pytest.raises(S.SchemaError):
        S.decode_unknown_sync(generated.Kind)("z")


def test_suspended_recursion():
    generated = _load(
        """
export type Tree = { readonly "children": ReadonlyArray<Tree> }
export const Tree = Schema.Struct({
  "children": Schema.Array(Schema.suspend((): Schema.Codec<Tree> => Tree))
})
"""
    )
    tree: dict[str, Any] = {"children": [{"children": []}]}
    assert S.decode_unknown_sync(generated.Tree)(tree) == {"children": ({"children": ()},)}


@pytest.mark.parametrize(
    "schema",
    [
        "Schema.Mystery(1)",
        "Schema.String.check(1 + 2)",
        'Schema.String.check(Schema.isPattern(new RegExp("^\\\\d+$")))',
        'Schema.String.check(Schema.isPattern(new RegExp("^a.b$")))',
    ],
)
def test_unknown_shape_names_the_declaration(schema: str):
    """An unknown call (emitting), an unknown character (reading) and a
    pattern JavaScript reads differently all name the declaration."""
    source = f"export type Odd = string\nexport const Odd = {schema}\n"
    with pytest.raises(gen.GenerateError, match=r"^Odd: "):
        gen.generate(source)


def test_no_declarations():
    with pytest.raises(gen.GenerateError):
        gen.generate("export type Nothing = string\n")


@pytest.mark.skipif(
    not gen.default_source().exists(), reason="no Effect reference checkout at $PYFECT_REF"
)
def test_checked_in_package_is_fresh():
    assert gen.main(["--check"]) == 0


def test_patterns_read_as_javascript():
    """A ``$`` ends the input, as in JavaScript (Python's ``$`` also
    matches before a final newline); messages show the JavaScript
    source."""
    generated = _load(
        "export type Name = string\n"
        'export const Name = Schema.String.check(Schema.isPattern(new RegExp("^[a-z]+$")))\n'
    )
    decode = S.decode_unknown_sync(generated.Name)
    assert decode("abc") == "abc"
    with pytest.raises(S.SchemaError, match=r"a string matching the RegExp \^\[a-z\]\+\$"):
        decode("abc\n")
