"""``codegen.Module``, the replacement for ``representation.to_code_document``
(deprecated since Effect 4.1.5 moved it to ``Codegen``)."""

from __future__ import annotations

import enum
import re
import warnings
from typing import Any, NotRequired, TypedDict

import pytest

from pyfect import codegen
from pyfect import schema as S
from pyfect.codegen import DeclarationBinding, import_named
from pyfect.schema import representation as R
from pyfect.schema.representation._code_document import code_document


class _Point(TypedDict):
    x: float


Point = S.Struct(_Point).annotate(identifier="Point")


def _run(source: str) -> dict[str, Any]:
    namespace: dict[str, Any] = {"__name__": "generated"}
    exec(source, namespace)
    return namespace


def test_prints_each_schema_as_a_variable_of_its_name_sharing_references() -> None:
    document = R.to_representations((Point, S.Array(Point)))
    first, second = document.representations
    module = codegen.Module()
    module.add_schemas({"One": first}, references=document.references)
    module.add_schemas({"Many": second}, references=document.references)
    source = module.print()
    assert source == R.to_code_module(code_document(document), names=("One", "Many"))
    namespace = _run(source)
    assert S.decode_unknown_sync(namespace["Many"])([{"x": 1}]) == ({"x": 1},)


def test_refuses_a_name_added_twice() -> None:
    module = codegen.Module()
    module.add_schemas({"A": R.to_representation(S.String).representation})
    with pytest.raises(ValueError, match="A schema named 'A' was already added"):
        module.add_schemas({"A": R.to_representation(S.Number).representation})


def test_refuses_a_reference_defined_differently() -> None:
    first = R.to_representations((Point,))
    module = codegen.Module()
    module.add_schemas({"A": first.representations[0]}, references=first.references)
    [ref] = first.references
    other = {ref: R.to_representation(S.String).representation}
    with pytest.raises(ValueError, match=f"The reference '{ref}' was already defined differently"):
        module.add_schemas({"B": first.representations[0]}, references=other)


def test_refuses_to_print_an_empty_module() -> None:
    with pytest.raises(ValueError, match="needs at least one schema"):
        codegen.Module().print()


def test_the_deprecated_functions_warn_and_still_work() -> None:
    document = R.to_representations((S.String,))
    with pytest.warns(DeprecationWarning, match="removed in 0.8.0: use codegen.Module"):
        old = R.to_code_document(document)  # pyright: ignore[reportDeprecated]
    assert old == code_document(document)
    with pytest.warns(DeprecationWarning, match=r"removed in 0.8.0: use Code\(runtime, type\)"):
        made = R.make_code("S.String", "str")  # pyright: ignore[reportDeprecated]
    assert made == R.Code("S.String", "str")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        module = codegen.Module()
        module.add_schemas({"A": document.representations[0]})
        module.print()


def test_the_deprecated_bindings_argument_warns_and_still_fills() -> None:
    bindings: dict[str, DeclarationBinding] = {}
    module = codegen.Module()
    string = R.to_representation(S.String).representation
    with pytest.warns(DeprecationWarning, match=r"removed in 0.8.0: use the mapping add_schemas"):
        returned = module.add_schemas({"A": string}, bindings=bindings)  # pyright: ignore[reportDeprecated]
    assert bindings == returned
    assert bindings["A"].name == "A"


code = codegen.code


class _Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


class _Tree(TypedDict):
    value: float
    children: tuple[_Tree, ...]


Tree: Any = S.Struct(_Tree, value=S.Number, children=S.Array(S.suspend(lambda: Tree))).annotate(
    identifier="Tree"
)


class _User(TypedDict):
    name: str
    nickname: NotRequired[str]
    color: _Color
    tags: dict[str, int]


User = S.Struct(
    _User,
    name=S.String.check(S.is_min_length(1)),
    nickname=S.String,
    color=S.Enum(_Color),
    tags=S.Record(S.String, S.Int),
).annotate(identifier="User")

# pyfect-dev 0.6.37's print of _golden_module(), byte for byte.
_GOLDEN = (
    "from __future__ import annotations\n"
    "\n"
    "import enum\n"
    "import pyfect as fx\n"
    "import re\n"
    "from typing import Any, Literal, NotRequired, TypedDict\n"
    "from pyfect import duration\n"
    "\n"
    "from pyfect import schema as S\n"
    "\n"
    "type UserType = _Struct\n"
    "type TreeType = _Struct1\n"
    "type AccountType = UserType\n"
    "type AccountsType = tuple[UserType, ...]\n"
    "type MaybeType = fx.Option[str]\n"
    "type ForestType = TreeType\n"
    'type LetterType = Literal["a"] | Literal["b"]\n'
    "type XsType = str\n"
    "type WaitType = duration.Duration\n"
    '_Enum = enum.Enum("_Enum", {"RED": "red", "BLUE": "blue"})\n'
    '_Struct = TypedDict("_Struct", {"name": str, "nickname": NotRequired[str], "color": _Enum, "tags": dict[str, float]})\n'  # noqa: E501
    '_Struct1 = TypedDict("_Struct1", {"value": float, "children": tuple[TreeType, ...]})\n'
    'User = S.Struct(_Struct, name=S.String.check(S.is_min_length(1).annotate(expected="a value with a length of at least 1")), nickname=S.String, color=S.Enum(_Enum), tags=S.Record(S.String, S.Number.check(S.is_int().annotate(expected="an integer")))).annotate(identifier="User")\n'  # noqa: E501
    'Tree: S.Bottom[TreeType, Any, Any, Any] = S.Struct(_Struct1, value=S.Number, children=S.Array(S.suspend(lambda: Tree))).annotate(identifier="Tree")\n'  # noqa: E501
    "Account = User\n"
    "Accounts = S.Array(User)\n"
    'Maybe = S.Option(S.String).annotate(expected="Option")\n'
    "Forest = Tree\n"
    'Letter = S.Literals(["a", "b"])\n'
    'Xs = S.String.check(S.is_pattern(re.compile("^x+$", 32)).annotate(expected="a string matching the RegExp ^x+$"))\n'  # noqa: E501
    'Wait = S.Duration.annotate(expected="Duration")\n'
)


def _golden_module() -> codegen.Module:
    first = R.to_representations((User, S.Array(User), S.Option(S.String)))
    second = R.to_representations(
        (
            Tree,
            S.Union([S.Literal("a"), S.Literal("b")]),
            S.String.check(S.is_pattern(re.compile(r"^x+$"))),
            S.Duration,
        )
    )
    accounts, many, maybe = first.representations
    forest, letter, xs, wait = second.representations
    module = codegen.Module()
    module.add_schemas(
        {"Account": accounts, "Accounts": many, "Maybe": maybe}, references=first.references
    )
    module.add_schemas(
        {"Forest": forest, "Letter": letter, "Xs": xs, "Wait": wait},
        references=second.references,
    )
    return module


def test_a_module_of_schemas_prints_as_0_6_37_did() -> None:
    """``add_schemas`` returns the bindings since 0.7.0; the module prints the same."""
    assert _golden_module().print() == _GOLDEN


def test_bindings_name_the_printed_schemas() -> None:
    document = R.to_representations((S.String, S.Number))
    module = codegen.Module()
    bindings = module.add_schemas(
        {"Name": document.representations[0], "filter": document.representations[1]}
    )
    assert {name: b.name for name, b in bindings.items()} == {"Name": "Name", "filter": "filter"}
    assert "filter = S.Number" in module.print()


def test_effects_example_schemas_then_a_declaration() -> None:
    document = R.to_representation(S.String)
    module = codegen.Module()
    schemas = module.add_schemas({"User": document.representation}, references=document.references)
    user = schemas.get("User")
    assert user is not None
    alias = module.declare("User")
    source = module.define(alias, [code(alias, " = ", user)], [user]).print()
    assert source == (
        "from pyfect import schema as S\n\ntype UserType = str\n\nUser = S.String\n\nUser1 = User\n"
    )


def test_a_declaration_then_schemas() -> None:
    module = codegen.Module()
    taken = module.declare("User")
    typed = module.declare("S")
    module.define(taken, [code(taken, " = ", typed)], [typed])
    module.define(typed, [code(typed, " = 1")])
    schemas = module.add_schemas({"User": R.to_representation(S.String).representation})
    assert schemas["User"].name == "User1"
    source = module.print()
    assert source == (
        "from pyfect import schema as S1\n\n"
        "S = 1\n\n"
        "User = S\n\n"
        "type User1Type = str\n\n"
        "User1 = S1.String\n"
    )
    namespace = _run(source)
    assert namespace["User"] == 1
    assert S.is_(namespace["User1"])("ok")


def test_schema_and_declaration_imports_merge() -> None:
    module = codegen.Module()
    cast = import_named("typing", "cast")
    literal = module.add_import(codegen.NamedImport("typing", "Literal", "Literal"))
    first = module.declare("first")
    module.define(first, [code(first, ": ", literal, '["a"] = ', cast, '(str, "a")')])
    module.add_schemas(
        {"Letter": R.to_representation(S.Literal("a")).representation},
    )
    source = module.print()
    assert source.splitlines()[:2] == [
        "from typing import Literal, cast",
        "from pyfect import schema as S",
    ]
    assert 'type LetterType = Literal["a"]' in source


def test_a_name_declared_before_the_schemas_reads_them() -> None:
    module = codegen.Module()
    reader = module.declare("reader")
    schemas = module.add_schemas({"Name": R.to_representation(S.String).representation})
    name = schemas["Name"]
    module.define(reader, [code(reader, " = ", name)], [name])
    source = module.print()
    assert source.index("Name = S.String") < source.index("reader = Name")
    namespace = _run(source)
    assert namespace["reader"] is namespace["Name"]


def test_type_only_writes_the_types() -> None:
    document = R.to_representations((Tree, User))
    module = codegen.Module()
    schemas = module.add_schemas(
        {"Forest": document.representations[0], "Account": document.representations[1]},
        references=document.references,
        type_only=True,
    )
    source = module.print()
    assert "S." not in source
    assert "from pyfect import schema" not in source
    assert {name: b.name for name, b in schemas.items()} == {
        "Forest": "ForestType",
        "Account": "AccountType",
    }
    namespace = _run(source)
    user = namespace["AccountType"].__value__.__value__
    assert set(user.__annotations__) == {"name", "nickname", "color", "tags"}


def test_a_reference_shared_with_a_type_only_call_keeps_its_value() -> None:
    document = R.to_representations((User,))
    module = codegen.Module()
    module.add_schemas(
        {"Types": document.representations[0]}, references=document.references, type_only=True
    )
    module.add_schemas({"Values": document.representations[0]}, references=document.references)
    namespace = _run(module.print())
    assert namespace["Values"] is namespace["User"]
    assert "Types" not in namespace


def test_a_schema_that_is_its_own_reference_is_that_reference() -> None:
    document = R.to_representations((User,))
    module = codegen.Module()
    schemas = module.add_schemas(
        {"User": document.representations[0]}, references=document.references
    )
    user = schemas["User"]
    assert user.name == "User"
    with pytest.raises(ValueError, match="Duplicate definition: User"):
        module.define(user, ["User = 1"])
    namespace = _run(module.print())
    value: dict[str, object] = {"name": "a", "color": namespace["_Enum"]("red"), "tags": {}}
    assert S.is_(namespace["User"])(value)


def test_an_unprintable_schema_raises_when_printed_with_declarations() -> None:
    representation = R.Declaration()
    module = codegen.Module()
    module.add_schemas({"A": representation})
    module.add("x = 1")
    with pytest.raises(R.RepresentationError, match="Missing to_code callback"):
        module.print()


def test_a_schema_leaves_the_reserved_names_alone() -> None:
    module = codegen.Module(["Client"])
    schemas = module.add_schemas({"Client": R.to_representation(S.String).representation})
    assert schemas["Client"].name == "Client1"
    assert "Client1 = S.String" in module.print()


def test_a_renamed_import_after_text_beyond_ascii() -> None:
    module = codegen.Module()
    taken = module.declare("S")
    module.define(taken, [code(taken, " = 0")])
    letters = S.Union([S.Literal("é𝄞"), S.Literal(1), S.String])
    module.add_schemas({"Letters": R.to_representation(letters).representation})
    source = module.print()
    assert 'S1.Union([S1.Literal("é𝄞"), S1.Literal(1), S1.String])' in source
    assert S.is_(_run(source)["Letters"])("é𝄞")
