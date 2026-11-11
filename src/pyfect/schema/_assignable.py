"""Whether the values one schema decodes to are values of another's type, for
``Struct(TypedDict, key=schema)``: the given schema's decoded side must fit
the key's annotation. Pyright cannot check it (a keyword argument cannot be
typed by a TypedDict key, ``research/typing/schema_6_struct_overrides.py``),
so ``Struct`` does, when the struct is made.

``assignable(sub, sup)`` answers ``True``, ``False`` or ``None`` (cannot
tell). Only a definite ``False`` is an error, so a node this does not know
(a declaration, a suspension) never rejects a struct.
"""

from __future__ import annotations

from collections.abc import Iterable

from pyfect.exit import Success
from pyfect.schema import ast
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast._result import run_now

type Answer = bool | None

_KEYWORDS = (ast.String, ast.Number, ast.Boolean, ast.Null, ast.BigInt)
_LEAVES = (*_KEYWORDS, ast.Literal, ast.Enum, ast.Arrays, ast.Objects)
_NO_OPTIONS: ParseOptions = {}


def assignable(sub: ast.AST, sup: ast.AST) -> Answer:
    """Whether every value ``sub`` decodes to is one ``sup`` accepts (both
    decoded sides)."""
    sup = sup.to_type()
    if isinstance(sup, (ast.Any, ast.Unknown)) and not sup.checks:
        return True  # before ``to_type`` walks a deeply nested ``sub``
    sub = sub.to_type()
    if isinstance(sub, (ast.Any, ast.Never)):
        return True
    if isinstance(sub, ast.Union):
        return _all(assignable(member, sup) for member in sub.types)
    if isinstance(sup, ast.Union):
        return _any(assignable(sub, member) for member in sup.types)
    return _literal(sub, sup) if isinstance(sub, ast.Literal) else _leaves(sub, sup)


def _leaves(sub: ast.AST, sup: ast.AST) -> Answer:
    if not (isinstance(sub, _LEAVES) and isinstance(sup, _LEAVES)):
        return None
    if type(sub) is not type(sup):
        # Two different kinds of value, but a ``bool`` is an ``int`` and an
        # ``int`` (BigInt) a Number to Python.
        return None if {type(sub), type(sup)} <= {ast.Number, ast.BigInt, ast.Boolean} else False
    return _same_kind(sub, sup)


def _literal(sub: ast.Literal, sup: ast.AST) -> Answer:
    if isinstance(sup, ast.Literal):
        return ast.same_literal(sup.literal, sub.literal) and _checks_kept(sub, sup)
    if isinstance(sup, _KEYWORDS):
        return type(run_now(sup.parse(sub.literal, _NO_OPTIONS))) is Success
    if isinstance(sup, _LEAVES):
        return False
    return None


def _same_kind(sub: ast.AST, sup: ast.AST) -> Answer:
    if not _checks_kept(sub, sup):
        return False
    if isinstance(sub, ast.Enum) and isinstance(sup, ast.Enum):
        return sub.enum is sup.enum
    if isinstance(sub, ast.Arrays) and isinstance(sup, ast.Arrays):
        return _arrays(sub, sup)
    if isinstance(sub, ast.Objects) and isinstance(sup, ast.Objects):
        return _objects(sub, sup)
    return True


def _checks_kept(sub: ast.AST, sup: ast.AST) -> bool:
    """``sup``'s checks all run on ``sub`` too (the same check objects: a
    schema refined from another keeps its checks)."""
    kept = {id(check) for check in sub.checks or ()}
    return all(id(check) in kept for check in sup.checks or ())


def _arrays(sub: ast.Arrays, sup: ast.Arrays) -> Answer:
    if sup.mutable and not sub.mutable:
        return False  # a tuple is not a list (a list may be a ``Sequence``)
    if len(sub.elements) != len(sup.elements) or len(sub.rest) != len(sup.rest):
        return None
    pairs = [(a.type, b.type) for a, b in zip(sub.elements, sup.elements, strict=True)]
    pairs += list(zip(sub.rest, sup.rest, strict=True))
    return _all(assignable(a, b) for a, b in pairs)


def _objects(sub: ast.Objects, sup: ast.Objects) -> Answer:
    if sub.index_signatures or sup.index_signatures:
        return None
    own = {p.name: p for p in sub.properties}
    answers: list[Answer] = []
    for wanted in sup.properties:
        found = own.get(wanted.name)
        if found is None:
            answers.append(None if wanted.optional else False)
        else:
            answers.append(assignable(found.type, wanted.type))
    return _all(answers)


def _all(answers: Iterable[Answer]) -> Answer:
    seen = list(answers)
    if False in seen:
        return False
    return None if None in seen else True


def _any(answers: Iterable[Answer]) -> Answer:
    seen = list(answers)
    if True in seen:
        return True
    return None if None in seen else False
