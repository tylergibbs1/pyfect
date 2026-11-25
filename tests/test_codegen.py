"""``codegen.Module``, the replacement for ``representation.to_code_document``
(deprecated since Effect 4.1.5 moved it to ``Codegen``)."""

from __future__ import annotations

import warnings
from typing import Any, TypedDict

import pytest

from pyfect import codegen
from pyfect import schema as S
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
    module = codegen.Module().add_schemas({"One": first}, references=document.references)
    source = module.add_schemas({"Many": second}, references=document.references).print()
    assert source == R.to_code_module(code_document(document), names=("One", "Many"))
    namespace = _run(source)
    assert S.decode_unknown_sync(namespace["Many"])([{"x": 1}]) == ({"x": 1},)


def test_refuses_a_name_added_twice() -> None:
    module = codegen.Module().add_schemas({"A": R.to_representation(S.String).representation})
    with pytest.raises(ValueError, match="A schema named 'A' was already added"):
        module.add_schemas({"A": R.to_representation(S.Number).representation})


def test_refuses_a_reference_defined_differently() -> None:
    first = R.to_representations((Point,))
    module = codegen.Module().add_schemas(
        {"A": first.representations[0]}, references=first.references
    )
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
        code = R.make_code("S.String", "str")  # pyright: ignore[reportDeprecated]
    assert code == R.Code("S.String", "str")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        codegen.Module().add_schemas({"A": document.representations[0]}).print()
