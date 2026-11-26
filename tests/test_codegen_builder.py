"""``effect/test/Codegen.test.ts``: the ``codegen.Module`` builder and schemas sharing a
module with declarations, with the expected source spelled in Python.

Mappings (``pyfect.codegen``'s docstring): a namespace import is ``import m as X``, a
named one ``from m import x``, a type-only one goes under ``if TYPE_CHECKING:``,
``indent`` indents four spaces and ``doc_comment`` writes a docstring. ``propertyKey``
and ``importDefault`` have no Python counterpart, so their assertions are left out; where
Effect reserves ``globalThis`` and declares the keyword ``default``, these use the builtin
``float`` and the keyword ``class``.

pyfect has no symbols, so the schema titles leave out the unique symbol shared between
schemas; a schema's type is ``XType`` beside its value ``X``, and Effect's ``declare enum``
is the ``enum.Enum`` the types name. Effect checks the generated modules with ``tsc``;
``test_generated_schema_modules_type_check`` runs pyright on them.
"""

from __future__ import annotations

import enum
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect.codegen import (
    DeclarationBinding,
    Module,
    NamedImport,
    NamespaceImport,
    code,
    deferred,
    doc_comment,
    import_named,
    import_namespace,
    indent,
    join,
    literal,
)
from pyfect.option import Some
from pyfect.schema import representation as R


def test_independent_modules() -> None:
    """keeps independently created modules isolated"""
    first = Module()
    second = Module()
    a = first.declare("A")
    b = second.declare("A")
    assert first.define(a, [code(a, " = 1")]) is first
    second.define(b, [code(b, " = 2")])

    assert first.print() == "A = 1\n"
    assert second.print() == "A = 2\n"
    with pytest.raises(ValueError, match="Expected a declaration binding owned by this module"):
        second.define(a, ["1"])
    with pytest.raises(ValueError, match="Scope belongs to another module"):
        second.declare("x", scope=first.scope())


def test_accumulating_after_finalization() -> None:
    """can keep accumulating after finalization without changing previous output"""
    module = Module()
    tools = import_namespace("tools", "Tools")
    module.add(code("use(", tools, ".value)"))
    first = module.finalize()

    local = module.declare("Tools")
    module.define(local, [code(local, " = 1")])
    second = module.finalize()

    assert first.imports == ("import tools as Tools",)
    assert first.body == ("use(Tools.value)",)
    assert first.declarations == ()
    assert local not in first.names
    assert first.names[tools] == "Tools"
    assert second.imports == ("import tools as Tools1",)
    assert second.body == ("use(Tools1.value)",)
    assert [d.fragments for d in second.declarations] == [("Tools = 1",)]
    assert second.names[tools] == "Tools1"


def test_dependency_order() -> None:
    """resolves bindings and dependency order without changing literal text"""
    module = Module()
    child = module.declare("Option")
    parent = module.declare("await")
    with pytest.raises(TypeError, match="Code fragments must be rendered by their module"):
        str(child)
    imported = module.add_import(NamespaceImport("effect.Option", "Option"))
    module.define(parent, [code(parent, " = ", imported, ".some(", child, ")")], [child, imported])
    module.define(child, [code(child, ' = {"Option": "Option"}')])
    output = module.finalize([parent])
    assert [d.fragments for d in output.declarations] == [
        ('Option = {"Option": "Option"}',),
        ("await1 = Option1.some(Option)",),
    ]
    assert output.roots == ("await1",)


def test_shared_fragments_render_once() -> None:
    """renders shared fragments once per finalization"""
    module = Module()
    calls = 0

    def value(_: object) -> str:
        nonlocal calls
        calls += 1
        return "value"

    fragment = deferred(value)
    for _ in range(12):
        fragment = code(fragment, fragment)
    assert module.finalize([fragment]).roots[0] == "value" * 4096
    assert calls == 1
    assert module.finalize([fragment]).roots[0] == "value" * 4096
    assert calls == 2


def test_cycles_and_imports_of_one_name() -> None:
    """rejects eager cycles and distinguishes imports requesting the same name"""
    module = Module()
    a = module.declare("A")
    b = module.declare("B")
    module.define(a, [b], [b])
    module.define(b, [a], [a])
    with pytest.raises(ValueError, match="Cyclic initialization dependency"):
        module.finalize([])

    request = NamespaceImport("one", "Value")
    imports = Module()
    first = imports.add_import(request)
    assert imports.add_import(request) is first
    second = imports.add_import(NamespaceImport("two", "Value"))
    output = imports.finalize([code(first, ".value + ", second, ".value")])
    assert output.roots == ("Value.value + Value1.value",)
    assert output.imports == ("import one as Value", "import two as Value1")


def test_import_symbols_shared_across_modules() -> None:
    """shares import symbols across modules and prints without mutating names"""
    effect = import_namespace("effect.Effect", "Effect")
    with pytest.raises(TypeError, match="Code fragments must be rendered by their module"):
        f"{effect}"
    for collision in (True, False):
        module = Module()
        if collision:
            module.declare("Effect", exact=True)
        module.add(code("one = ", effect, ".succeed(1)"))
        name = "Effect1" if collision else "Effect"
        expected = f"import effect.Effect as {name}\n\none = {name}.succeed(1)\n"
        assert module.print() == expected
        assert module.print() == expected
    local = Module().declare("Local")
    with pytest.raises(ValueError, match="Binding belongs to another module"):
        Module().finalize([local])


def test_used_imports_grouped_and_promoted() -> None:
    """emits only used imports, groups named imports, and promotes type imports"""
    module = Module()
    assert module.add_side_effect("setup").add_side_effect("setup") is module
    module.add_import(NamespaceImport("unused", "Unused"))
    option = import_named("effect.Option", "Option", type_only=True)
    some = import_named("effect.Option", "some")
    effect_type = import_namespace("effect.Effect", "Effect", type_only=True)
    effect_value = import_namespace("effect.Effect", "OtherName")
    example = import_namespace("example", "Example", type_only=True)
    output = module.finalize(
        [code(option, " ", some, " ", effect_type, " ", effect_value, " ", example)]
    )
    assert output.imports == (
        "from __future__ import annotations",
        "import setup",
        "from effect.Option import some",
        "import effect.Effect as Effect",
        "from typing import TYPE_CHECKING",
        "if TYPE_CHECKING:\n    from effect.Option import Option\n    import example as Example",
    )
    assert output.roots == ("Option some Effect Effect Example",)


def test_exact_names_and_nested_scopes() -> None:
    """keeps exact names and prevents shadowing along nested scopes"""
    module = Module(["Client"])
    outer = module.scope()
    inner = module.scope(outer)
    sibling = module.scope()
    bindings = [
        module.declare("x", scope=inner),
        module.declare("x", scope=outer),
        module.declare("x"),
        module.declare("x", scope=sibling),
        module.declare("user-id"),
        module.declare("float"),
    ]
    assert module.finalize(bindings).roots == ("x", "x1", "x2", "x", "user_id", "float1")
    for name in ("Client", "x", "class", "invalid-name"):
        with pytest.raises(ValueError, match="Cannot declare exact name"):
            module.declare(name, exact=True)
    name = module.declare("invalid_name", exact=True)
    assert name.name == "invalid_name"
    assert module.finalize([name]).roots == ("invalid_name",)


def test_literals_documentation_and_indentation() -> None:
    """formats literals, keys, documentation, and indented fragments"""
    values = ['a"b', -0.0, float("nan"), float("inf"), float("-inf"), -12, True, None]
    assert [literal(value) for value in values] == [
        '"a\\"b"',
        "-0.0",
        'float("nan")',
        'float("inf")',
        '-float("inf")',
        "-12",
        "True",
        "None",
    ]
    assert doc_comment('one """') == '"""one \\"\\"\\""""\n'
    assert doc_comment(" \n") == ""
    module = Module()
    assert module.finalize([code("values ", [1, None, False, ["ok"]])]).roots == ("values 1ok",)
    fields = join([code(doc_comment(["A user.", "", "Has an id."]), "id: str"), "age: int"], "\n")
    assert module.add(code("class User(TypedDict):", indent(code("\n", fields)))) is module
    assert module.print() == (
        'class User(TypedDict):\n    """A user.\n\n    Has an id.\n    """\n'
        "    id: str\n    age: int\n"
    )
    with pytest.raises(TypeError, match="Code fragments must be rendered by their module"):
        str(fields)


def test_printed_source_runs() -> None:
    """The printed module is Python that runs: imports, dependency order, literals
    of every kind and a docstring with quotes and backslashes."""
    module = Module()
    path = import_named("pathlib", "PurePosixPath")
    text = 'quote " and \\ and \x00 and """'
    base = module.declare("base")
    derived = module.declare("derived")
    module.define(derived, [code(derived, " = ", path, "(", base, ") / 'b'")], [base, path])
    module.define(base, [code(base, " = ", literal("a"))])
    module.add(code("TEXT = ", literal(text)))
    module.add(code("NAN = ", literal(float("nan"))))
    module.add(code("def f():", indent(code("\n", doc_comment(text), "return 1"))))
    namespace: dict[str, object] = {}
    exec(module.print(), namespace)
    assert str(namespace["derived"]) == "a/b"
    assert namespace["TEXT"] == text
    assert namespace["NAN"] != namespace["NAN"]
    assert getattr(namespace["f"], "__doc__", None) == text


def test_imports_spelled_in_python() -> None:
    """Relative modules, provided imports and side effects bind what they name."""
    module = Module()
    sibling = module.add_import(NamespaceImport(".models.user", "User"))
    parent = module.add_import(NamedImport("..", "config", "config"))
    provided = module.provide_import(NamespaceImport("json", "json_module"))
    module.add_side_effect("logging.config")
    logging = module.add_import(NamespaceImport("logging", "logging"))
    output = module.finalize([code(sibling, parent, provided, logging)])
    assert output.imports == (
        "from .models import user as User",
        "from .. import config",
        "import logging.config",
        "import logging as logging1",
    )
    assert output.roots == ("Userconfigjson_modulelogging1",)
    with pytest.raises(ValueError, match="Conflicting predefined import: json_module"):
        module.provide_import(NamespaceImport("other", "json_module"))
    with pytest.raises(ValueError, match=r"'1x' in 'a\.1x' is not a Python name"):
        NamespaceImport("a.1x", "X")


def test_an_empty_module_refuses_to_print() -> None:
    """A module with no schema, declaration or appended source has nothing to print."""
    with pytest.raises(ValueError, match="needs at least one schema"):
        Module().print()


class _Color(enum.Enum):
    RED = 1
    BLUE = 2


class _Root(TypedDict):
    o: fx.Option[str]
    n: int
    state: _Color


_ROOT = S.Struct(_Root, o=S.Option(S.String), n=S.Int, state=S.Enum(_Color)).annotate(
    identifier="Root"
)


class _Tree(TypedDict):
    children: tuple[_Tree, ...]


_TREE: Any = S.Struct(_Tree, children=S.Array(S.suspend(lambda: _TREE))).annotate(identifier="Tree")


def _run(source: str) -> dict[str, Any]:
    namespace: dict[str, Any] = {"__name__": "generated"}
    exec(source, namespace)
    return namespace


def _shared_sources() -> tuple[str, str, dict[str, DeclarationBinding]]:
    document = R.to_representations((_ROOT, S.Number, S.String))
    given = {
        "Root": document.representations[0],
        "1": document.representations[1],
        "user-id": document.representations[2],
    }
    module = Module()
    helper = module.declare("Root")
    module.define(helper, [code(helper, " = 0")])
    schemas: dict[str, DeclarationBinding] = {}
    module.add_schemas(given, references=document.references, bindings=schemas)
    root = schemas["Root"]
    consumer = module.declare("Consumer")
    module.define(consumer, [code(consumer, " = ", root)], [root])
    for name in ("S", "fx"):
        local = module.declare(name)
        module.define(local, [code(local, " = 0")])
    types = Module().add_schemas(given, references=document.references, type_only=True)
    return module.print(), types.print(), schemas


def _recursive_source() -> tuple[str, dict[str, DeclarationBinding]]:
    document = R.to_representations((S.Array(_TREE), _TREE))
    schemas: dict[str, DeclarationBinding] = {}
    module = Module().add_schemas(
        {"Forest": document.representations[0], "Tree": document.representations[1]},
        references=document.references,
        bindings=schemas,
    )
    return module.print(), schemas


def test_schemas_share_the_module() -> None:
    """shares names, imports and symbol identities with the rest of the module"""
    source, type_source, schemas = _shared_sources()
    root = schemas["Root"]
    assert root.name == "Root1"
    generated = _run(source)
    root_schema = generated[root.name]
    assert generated["Consumer"] is root_schema
    assert generated["S"] == 0
    assert generated["fx"] == 0
    red = generated["_Enum"](1)
    value = {"o": Some("ok"), "n": 1, "state": red}
    assert S.decode_unknown_sync(root_schema)({"o": Some("ok"), "n": 1, "state": 1}) == value
    assert not S.is_(root_schema)({**value, "n": 1.5})
    number = generated[schemas["1"].name]
    string = generated[schemas["user-id"].name]
    assert (schemas["1"].name, schemas["user-id"].name) == ("_1", "user_id")
    assert S.is_(number)(42)
    assert not S.is_(number)("42")
    assert S.is_(string)("ok")
    assert not S.is_(string)(42)

    assert "S.Struct" not in type_source
    assert "enum.Enum(" in type_source
    assert "TypedDict(" in type_source
    _run(type_source)


def test_recursive_schemas() -> None:
    """preserves recursive schemas and initializes their eager consumers"""
    source, schemas = _recursive_source()
    generated = _run(source)
    value: dict[str, object] = {"children": [{"children": []}]}
    decoded = S.decode_unknown_sync(generated[schemas["Forest"].name])([value])
    assert decoded == ({"children": ({"children": ()},)},)
    assert not S.is_(generated[schemas["Tree"].name])({"children": [None]})


def test_generated_schema_modules_type_check(tmp_path: Path) -> None:
    """The modules of the two titles above pass pyright (Effect runs ``tsc`` on its own)."""
    source, type_source, _ = _shared_sources()
    recursive, _ = _recursive_source()
    files: list[str] = []
    for name, text in (("shared", source), ("types", type_source), ("recursive", recursive)):
        path = tmp_path / f"{name}.py"
        path.write_text(text)
        files.append(str(path))
    run = subprocess.run(
        [sys.executable, "-m", "pyright", "--outputjson", *files],
        capture_output=True,
        text=True,
        check=False,
        cwd=Path(__file__).parent.parent,
    )
    diagnostics = json.loads(run.stdout)["generalDiagnostics"]
    assert [d["message"] for d in diagnostics if d["severity"] == "error"] == []
