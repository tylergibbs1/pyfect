"""Guard: ``fn``, ``fn_untraced`` and ``fn("name")`` take pipeables, typed
so each sees the previous result (Effect's ``Effect.fn(body, ...pipeables)``).

Each pipeable has its own result type, which pyright can only spell as one
overload per number of pipeables. They are generated here, up to
``MAX_PIPEABLES``, between the ``generated`` markers of ``pyfect/_fn.py``,
and this test fails when the source differs from what is generated.

Regenerate with ``uv run python tests/test_fn_overloads.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pyfect as fx

MAX_PIPEABLES = 9
LINE_LENGTH = 100
SOURCE = Path(fx.__file__).parent / "_fn.py"

GEN_BODY = "Callable[P, Generator[Effect[Any, E, R], Any, A]]"
EFFECT_BODY = "Callable[P, Effect[A, E, R]]"


def _signature(name: str, indent: str, self_param: list[str], body: str, n: int) -> str:
    results = [f"B{i}" for i in range(1, n + 1)]
    type_params = ["**P", "A", *results, "E = Never", "R = Never"]
    previous = ["Effect[A, E, R]", *results]
    params = [*self_param, f"f: {body}"]
    params += [f"p{i}: Pipe[{previous[i - 1]}, B{i}, P]" for i in range(1, n + 1)]
    params.append("/")
    returns = f"Callable[P, {results[-1] if results else 'Effect[A, E, R]'}]"
    one_line = (
        f"{indent}def {name}[{', '.join(type_params)}]({', '.join(params)}) -> {returns}: ..."
    )
    head = f"{indent}@overload\n"
    if len(one_line) <= LINE_LENGTH:
        return head + one_line + "\n"
    inner = indent + "    "
    tps = f"{', '.join(type_params)}"
    opening = f"{indent}def {name}[{tps}]("
    if len(opening) > LINE_LENGTH:
        opening = f"{indent}def {name}[\n" + "".join(f"{inner}{t},\n" for t in type_params)
        opening += f"{indent}]("
    lines = "".join(f"{inner}{p},\n" for p in params)
    return head + opening + "\n" + lines + f"{indent}) -> {returns}: ...\n"


def render_fn() -> str:
    out = [_signature("fn", "", [], GEN_BODY, n) for n in range(MAX_PIPEABLES + 1)]
    out.append("@overload\ndef fn(name: str, /, **options: Unpack[SpanOptions]) -> _Traced: ...\n")
    return "".join(out)


def render_fn_untraced() -> str:
    return "".join(_signature("fn_untraced", "", [], GEN_BODY, n) for n in range(MAX_PIPEABLES + 1))


def render_traced() -> str:
    return "".join(
        _signature("__call__", "    ", ["self"], body, n)
        for n in range(MAX_PIPEABLES + 1)
        for body in (GEN_BODY, EFFECT_BODY)
    )


SECTIONS = {
    "_Traced.__call__": ("    ", render_traced),
    "fn": ("", render_fn),
    "fn_untraced": ("", render_fn_untraced),
}


def _markers(name: str, indent: str) -> tuple[str, str]:
    begin = f"{indent}# --- generated {name} overloads (tests/test_fn_overloads.py) ---\n"
    return begin, f"{indent}# --- end generated {name} overloads ---\n"


def generated(text: str) -> str:
    for name, (indent, render) in SECTIONS.items():
        begin, end = _markers(name, indent)
        start = text.index(begin) + len(begin)
        text = text[:start] + render() + text[text.index(end, start) :]
    return text


def test_fn_overloads_are_generated():
    text = SOURCE.read_text()
    assert text == generated(text), "run `uv run python tests/test_fn_overloads.py`"


if __name__ == "__main__":
    SOURCE.write_text(generated(SOURCE.read_text()))
    sys.exit(0)
