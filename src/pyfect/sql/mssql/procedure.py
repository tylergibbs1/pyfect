"""Stored procedure calls (Effect's ``@effect/sql-mssql`` ``Procedure``):
a procedure's name, its input and output parameters and the type of the
rows it returns, run with ``MssqlClientService.call``::

    name = Parameter[str]("name", TYPES.NVarChar)
    answer = Parameter[int]("answer", TYPES.Int)
    get_answer = procedure.make("get_answer").param(name).output_param(answer)

    result = yield client.call(get_answer.compile(name("Tim")))
    result.output[answer]  # an int
    result.rows  # the rows it selected

A parameter added again under the same name replaces the earlier one, as
in Effect's record of parameters. ``compile`` takes a value for each
input, and nothing else.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, overload

from pyfect.sql.connection import Row
from pyfect.sql.mssql.parameter import Bound, Parameter


def _with(
    parameters: tuple[Parameter[Any], ...], parameter: Parameter[Any]
) -> tuple[Parameter[Any], ...]:
    kept = tuple(p for p in parameters if p.name != parameter.name)
    return (*kept, parameter)


@dataclass(frozen=True, slots=True)
class Procedure[A = Row]:
    """A stored procedure whose rows are ``A``s."""

    name: str
    params: tuple[Parameter[Any], ...] = ()
    output_params: tuple[Parameter[Any], ...] = ()

    def param(self, parameter: Parameter[Any]) -> Procedure[A]:
        """With the input ``parameter``."""
        return Procedure(self.name, _with(self.params, parameter), self.output_params)

    def output_param(self, parameter: Parameter[Any]) -> Procedure[A]:
        """With the output ``parameter``."""
        return Procedure(self.name, self.params, _with(self.output_params, parameter))

    def with_rows[B](self, row: type[B]) -> Procedure[B]:
        """Its rows typed as ``row`` (Effect's ``withRows<A>()``)."""
        return Procedure(self.name, self.params, self.output_params)

    def compile(self, *values: Bound[Any]) -> ProcedureWithValues[A]:
        """This procedure with a value for each input; ``ValueError`` when one
        is missing, repeated or not an input of it."""
        bound: dict[str, object] = {}
        inputs = {p.name: p for p in self.params}
        for value in values:
            name = value.parameter.name
            if inputs.get(name) != value.parameter:
                raise ValueError(f"{name!r} is not an input of procedure {self.name!r}")
            if name in bound:
                raise ValueError(f"{name!r} is bound twice")
            bound[name] = value.value
        missing = [name for name in inputs if name not in bound]
        if missing:
            raise ValueError(f"procedure {self.name!r} needs values for {missing}")
        return ProcedureWithValues(self, bound)


@dataclass(frozen=True, slots=True)
class ProcedureWithValues[A = Row]:
    """A procedure and the values of its inputs, ready to ``call``."""

    procedure: Procedure[A]
    values: Mapping[str, object]


class Outputs(Mapping[str, object]):
    """The output parameters of a call, by parameter (typed) or by name."""

    __slots__ = ("_values",)

    def __init__(self, values: Mapping[str, object]) -> None:
        self._values = dict(values)

    @overload
    def __getitem__[T](self, key: Parameter[T]) -> T: ...
    @overload
    def __getitem__(self, key: str) -> object: ...
    def __getitem__(self, key: Parameter[Any] | str) -> object:
        return self._values[key if isinstance(key, str) else key.name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"Outputs({self._values!r})"


@dataclass(frozen=True, slots=True)
class Result[A = Row]:
    """What a call returns: its output parameters and its rows."""

    output: Outputs
    rows: Sequence[A]


def make(name: str) -> Procedure:
    """The procedure ``name``, without parameters."""
    return Procedure(name)


__all__ = ["Outputs", "Procedure", "ProcedureWithValues", "Result", "make"]
