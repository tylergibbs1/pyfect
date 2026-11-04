"""Stored procedure parameters (Effect's ``@effect/sql-mssql``
``Parameter``): a name, the SQL Server type it is sent as, and the Python
type of its value, which ``Parameter[A]`` carries::

    answer = Parameter[int]("answer", TYPES.Int)
    name = Parameter[str]("name", TYPES.NVarChar, ParameterOptions(length=50))

``name("Tim")`` binds an input's value (``Procedure.compile``); the output
of a call is read back with ``result.output[answer]``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pyfect.sql.mssql.types import DataType, ParameterOptions


@dataclass(frozen=True, slots=True)
class Bound[A]:
    """An input parameter and its value."""

    parameter: Parameter[A]
    value: A


@dataclass(frozen=True, slots=True)
class Parameter[A]:
    """A procedure parameter whose value is an ``A``."""

    name: str
    type: DataType
    options: ParameterOptions = field(default_factory=ParameterOptions)

    def __post_init__(self) -> None:
        if not self.name or self.name.startswith("@"):
            raise ValueError(f"a parameter name is not empty and has no '@', got {self.name!r}")

    def __call__(self, value: A) -> Bound[A]:
        """This parameter bound to ``value``."""
        return Bound(self, value)


__all__ = ["Bound", "Parameter"]
