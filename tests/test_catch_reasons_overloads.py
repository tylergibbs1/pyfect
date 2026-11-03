"""Guard: ``catch_reasons`` takes as many cases as Effect's does.

Effect's ``catchReasons`` takes a record with a handler per reason, so any
number of them. Each case has its own reason class and handler type, which
pyright can only spell as one overload per number of cases; hand-written
ones stopped at three (two for channels). The overloads are generated here,
up to ``MAX_CASES``, between the ``generated catch_reasons`` markers of each
module, and this test fails when the source differs from what is generated.

Regenerate with ``uv run python tests/test_catch_reasons_overloads.py``.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

import pyfect as fx

MAX_CASES = 8
LINE_LENGTH = 100
SRC = Path(fx.__file__).parent
BEGIN = "# --- generated catch_reasons overloads (tests/test_catch_reasons_overloads.py) ---\n"
END = "# --- end generated catch_reasons overloads ---\n"


def _names(prefix: str, n: int) -> list[str]:
    return [f"{prefix}{i}" for i in range(1, n + 1)]


def _overload(type_params: list[str], params: list[str], returns: str, args: list[str]) -> str:
    tps = "".join(f"    {p},\n" for p in type_params)
    ps = "".join(f"    {p},\n" for p in params)
    result = f"{returns}[{', '.join(args)}]"
    if len(f") -> {result}: ...") > LINE_LENGTH:  # exploded, as ruff keeps it
        result = returns + "[\n" + "".join(f"    {a},\n" for a in args) + "]"
    return f"@overload\ndef catch_reasons[\n{tps}](\n{ps}) -> {result}: ...\n"


@dataclass(frozen=True)
class _Module:
    path: str
    # The success type parameter of case i, or None when the cases share one.
    success: Callable[[int], str] | None
    case: Callable[[int, str], str]
    shared: list[str]
    # ``or_else``'s own success type parameter, if it has one.
    or_else_success: list[str]
    or_else: str
    # The type arguments of ``_CatchReason`` / ``_CatchReasonAll``, given
    # the union of the cases' successes (and of their reason classes).
    returns: Callable[[str], list[str]]
    returns_all: Callable[[str, str], list[str]]


def _render(module: _Module) -> str:
    out: list[str] = []
    for with_or_else in (False, True):
        for n in range(1, MAX_CASES + 1):
            ks = _names("K", n)
            succ = [module.success(i) for i in range(1, n + 1)] if module.success else []
            type_params = ["T: HasReason[Any]", *ks, *(["EO"] if with_or_else else []), *succ]
            type_params += module.or_else_success if with_or_else else []
            type_params += module.shared
            params = ["tag: type[T]"]
            params += [f"case{i}: {module.case(i, f'K{i}')}" for i in range(1, n + 1)]
            params.append("/")
            succ_union = " | ".join(succ)
            if with_or_else:
                params += ["*", f"or_else: {module.or_else}"]
                returns = ("_CatchReasonAll", module.returns_all(" | ".join(ks), succ_union))
            else:
                returns = ("_CatchReason", module.returns(succ_union))
            out.append(_overload(type_params, params, *returns))
    return "".join(out)


_EFFECT = _Module(
    path="_catch_reason.py",
    success=lambda i: f"B{i}",
    case=lambda i, k: f"tuple[type[{k}], Callable[[{k}, T], _Eff[B{i}, EE, RR]]]",
    shared=["EE = Never", "RR = Never"],
    or_else_success=["C"],
    or_else="Callable[[EO, T], _Eff[C, EE, RR]]",
    returns=lambda bs: [bs, "EE", "RR"],
    returns_all=lambda ks, bs: ["T", "T", ks, "EO", bs, "C", "EE", "RR"],
)
_STREAM = _Module(
    path="stream/_catch_reason.py",
    success=lambda i: f"A{i}",
    case=lambda i, k: f"tuple[type[{k}], Callable[[{k}, T], _S[A{i}, EE, RR]]]",
    shared=["EE = Never", "RR = Never"],
    or_else_success=["C"],
    or_else="Callable[[EO, T], _S[C, EE, RR]]",
    returns=lambda as_: [as_, "EE", "RR"],
    returns_all=lambda ks, as_: ["T", "T", ks, "EO", as_, "C", "EE", "RR"],
)
_CHANNEL = _Module(
    path="channel/_catch_reason.py",
    success=None,
    case=lambda _i, k: f"_Case[{k}, T, O2, EE, D2, I, IE, ID, RR]",
    shared=[
        "O2",
        "D2 = None",
        "I = object",
        "IE = object",
        "ID = object",
        "EE = Never",
        "RR = Never",
    ],
    or_else_success=[],
    or_else="Callable[[EO, T], _Ch[O2, EE, D2, I, IE, ID, RR]]",
    returns=lambda _: ["O2", "EE", "D2", "I", "IE", "ID", "RR"],
    returns_all=lambda ks, _: ["T", "T", ks, "EO", "O2", "EE", "D2", "I", "IE", "ID", "RR"],
)
MODULES = [_EFFECT, _STREAM, _CHANNEL]


def _split(text: str) -> tuple[str, str, str]:
    head, sep, rest = text.partition(BEGIN)
    body, sep2, tail = rest.partition(END)
    assert sep and sep2, "markers missing"
    return head, body, tail


def write() -> None:
    for module in MODULES:
        path = SRC / module.path
        head, _, tail = _split(path.read_text())
        path.write_text(head + BEGIN + _render(module) + END + tail)


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.path)
def test_the_generated_overloads_are_current(module: _Module) -> None:
    _, body, _ = _split((SRC / module.path).read_text())
    assert body == _render(module), "run: uv run python tests/test_catch_reasons_overloads.py"


if __name__ == "__main__":
    write()
    sys.exit(0)
