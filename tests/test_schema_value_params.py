"""A function taking a schema and a value of its Type takes the schema as
``Exact``, never as ``Codec[A, ...]`` beside a parameter typed ``A``.

``Codec`` is covariant in its Type, so pyright widens ``A`` to fit any value:
``jwt.sign(S.Struct(Claims), {"sub": 1}, key)`` passed for ``sub: str``
(FINDINGS-vault 2). ``pyfect.schema._exact.Exact`` fixes ``A`` to the schema's
Type, as Effect's ``S["Type"]`` does.
"""

from __future__ import annotations

import inspect
import re
import typing
from collections.abc import Callable, Iterator

from _pyfect_modules import modules

_SCHEMA_OF = re.compile(r"\b(?:Codec|Schema|Decoder|Bottom)\[\s*(\w+)\s*[,\]]")


def _functions() -> Iterator[tuple[str, Callable[..., object]]]:
    for module in modules():
        for name, value in vars(module).items():
            if getattr(value, "__module__", None) != module.__name__:
                continue
            if inspect.isfunction(value):
                yield f"{module.__name__}.{name}", value
            elif inspect.isclass(value):
                for member_name, member in vars(value).items():
                    if inspect.isfunction(member):
                        yield f"{module.__name__}.{name}.{member_name}", member


def _widening(function: Callable[..., object]) -> Iterator[str]:
    for signature_of in (function, *typing.get_overloads(function)):
        parameters = inspect.signature(signature_of).parameters
        type_params = {param.__name__ for param in signature_of.__type_params__}
        annotations = {
            name: parameter.annotation
            for name, parameter in parameters.items()
            if isinstance(parameter.annotation, str) and name != "self"
        }
        for name, annotation in annotations.items():
            for match in _SCHEMA_OF.finditer(annotation):
                type_var = match.group(1)
                if type_var not in type_params:
                    continue
                for other, other_annotation in annotations.items():
                    if other != name and other_annotation.strip() == type_var:
                        yield f"{name}: {annotation}, {other}: {other_annotation}"


def test_no_schema_parameter_lets_its_value_widen_the_type() -> None:
    found = [
        f"{qualified}({pair})"
        for qualified, function in _functions()
        for pair in _widening(function)
    ]
    assert found == []
