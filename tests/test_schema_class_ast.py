"""A schema class has an ``ast`` as every Effect schema does (``A.ast``), so
it can go where a schema's AST is asked for (``jit_compiler.enable``,
``aot_compiler.Target``)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

import pyfect.schema as S
from pyfect.schema import aot_compiler, jit_compiler
from pyfect.schema.compiler import _registry


@pytest.fixture
def fresh_registry() -> Iterator[None]:
    _registry.reset()
    yield
    _registry.reset()


class Expense(S.Class):
    id: str
    amount_cents: int


class Paid(S.TaggedClass):
    at: str


class Declined(S.TaggedError):
    reason: str


class Broken(S.Error):
    detail: str


@pytest.mark.parametrize("cls", [Expense, Paid, Declined, Broken])
def test_a_schema_class_has_its_schemas_ast(cls: type[S.Class]) -> None:
    assert cls.ast is cls.__codec__().ast


@pytest.mark.usefixtures("fresh_registry")
def test_the_jit_compiler_takes_a_classs_ast() -> None:
    jit_compiler.enable(Expense.ast)
    decoded = S.decode_unknown_sync(Expense)({"id": "e1", "amount_cents": 5})
    assert decoded == Expense(id="e1", amount_cents=5)


def test_the_aot_compiler_takes_a_classs_ast() -> None:
    assert "def " in aot_compiler.compile([aot_compiler.Target(Declined.ast, ["decode"])])


def test_an_instance_has_no_ast() -> None:
    with pytest.raises(AttributeError):
        getattr(Expense(id="e1", amount_cents=5), "ast")  # noqa: B009


def test_a_field_named_ast_is_the_instances_and_has_no_default() -> None:
    class Node(S.Class):
        ast: str

    with pytest.raises(TypeError):
        Node()  # pyright: ignore[reportCallIssue]
    assert Node(ast="x").ast == "x"
    assert S.decode_unknown_sync(Node)({"ast": "y"}) == Node(ast="y")


def test_an_adapted_class_has_the_classs_ast() -> None:
    assert S.to_standard_schema_v1(Expense).ast is Expense.ast
