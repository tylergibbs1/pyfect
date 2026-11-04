"""``scripts/gen_ai_schemas.py``: the schemas it writes for snippets of
Effect's ``Generated.ts`` behave as Effect's, a shape it does not know
fails naming the declaration (or the client operation), and the
checked-in ``generated`` packages are what the reference checkout
gives."""

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
    sys.path.insert(0, str(ROOT / "scripts"))  # it imports gen_ai_client
    spec = importlib.util.spec_from_file_location(
        "gen_ai_schemas", ROOT / "scripts" / "gen_ai_schemas.py"
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
    return _load_files(gen.generate(source))


def _load_files(files: dict[str, str]) -> types.SimpleNamespace:
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
        'Schema.String.check(Schema.isPattern(new RegExp("^\\\\bx$")))',
        'Schema.String.check(Schema.isPattern(new RegExp("^[\\\\D]$")))',
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
    not all(target.default_source().exists() for target in gen.TARGETS.values()),
    reason="no Effect reference checkout at $PYFECT_REF",
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


def test_digit_and_word_classes_are_ascii():
    """JavaScript's ``\\d`` and ``\\w`` match ASCII only, where Python's
    ``str`` patterns also take other scripts' digits and letters."""
    generated = _load(
        "export type Day = string\n"
        "export const Day = Schema.String.check("
        'Schema.isPattern(new RegExp("^\\\\d{2}-[\\\\w-]+\\\\D$")))\n'
    )
    decode = S.decode_unknown_sync(generated.Day)
    assert decode("12-a_b-c!") == "12-a_b-c!"
    for value in ["\u0661\u0662-ab!", "12-\u00e9!", "12-ab1"]:
        with pytest.raises(S.SchemaError):
            decode(value)


def test_typed_declaration():
    """Effect's generator config types some schemas as their own type
    (``export const X: Schema.Schema<X> = ...``); they are generated too."""
    generated = _load(
        "export type Name = string\n"
        "export const Name = Schema.String\n"
        "export type Alias = Name\n"
        "export const Alias: Schema.Schema<Alias> = Name\n"
    )
    assert S.decode_unknown_sync(generated.Alias)("a") == "a"


def test_empty_struct_type_is_open():
    """TypeScript's ``{}`` (Effect's ``Schema.Struct({})``) is any object,
    so the type takes any keys, where an empty ``TypedDict`` takes none."""
    files = gen.generate("export type Empty = {}\nexport const Empty = Schema.Struct({})\n")
    assert "type Empty = _abc.Mapping[str, _t.Any]\n" in files["types.py"]
    assert S.decode_unknown_sync(_load_files(files).Empty)({}) == {}


def test_unknown_declaration_fails():
    with pytest.raises(gen.GenerateError, match="unknown declaration"):
        gen.generate("export type Odd = string\nexport const Odd: Other = Schema.String\n")


_CLIENT = """
export type Thing = { readonly "id": string }
export const Thing = Schema.Struct({ "id": Schema.String })
export type GetThingParams = { readonly "q"?: string }
export const GetThingParams = Schema.Struct({ "q": Schema.optionalKey(Schema.String) })
export interface OperationConfig {}
export const make = (httpClient: HttpClient.HttpClient): ThingClient => {
  return {
    httpClient,
    "getThing": (id, options) =>
      HttpClientRequest.get(`/things/${id}`).pipe(
        HttpClientRequest.setUrlParams({ "q": options?.params?.["q"] as any }),
        withResponse(options?.config)(HttpClientResponse.matchStatus({
          "2xx": decodeSuccess(Thing),
          "404": decodeError("GetThing404", Thing),
          orElse: unexpectedStatus
        }))
      )%s
  }
}

export interface ThingClient {
  readonly httpClient: HttpClient.HttpClient
  /**
   * Gets a thing.
   */
  readonly "getThing": <Config extends OperationConfig>(
    id: string,
    options: { readonly params?: typeof GetThingParams.Encoded | undefined } | undefined
  ) => Effect.Effect<
    WithOptionalResponse<typeof Thing.Type, Config>,
    HttpClientError.HttpClientError
  >
}
"""

_THING = gen.Target("thing", "Thing", "Thing", client=True)


def test_client_operations():
    """A method per operation: path arguments in the path, query
    parameters from ``params``, the status cases, the interface's docs."""
    text = gen.generate(_CLIENT % "", _THING)["client.py"]
    assert (
        "_GET_THING = _c.Operation(\"GET\", url_params=('q', ), success=Thing, "
        "errors={404: ('GetThing404', Thing)})"
    ) in text
    assert 'return self._json(_GET_THING, f"/things/{id}", params, None, include_response)' in text
    assert '"""Gets a thing."""' in text
    compile(text, "client.py", "exec")


def test_unknown_client_operation_names_it():
    odd = """,
    "oddThing": (options) =>
      HttpClientRequest.get(`/odd`).pipe(
        mystery
      )"""
    with pytest.raises(gen.GenerateError, match=r"^oddThing: unknown response handling"):
        gen.generate(_CLIENT % odd, _THING)
