"""(pyfect) A YAML flow collection over many lines holds one line at a time.

It used to append each line to the text it had read, copying it all once per line: quadratic,
but a copy costs so little per character against the parser's per-line work that time only
shows it past tens of thousands of lines. So the work is counted instead: the text held never
outgrows the line being read.
"""

from __future__ import annotations

import pytest

from pyfect.encoding import yaml
from pyfect.encoding.yaml import _FlowParser  # pyright: ignore[reportPrivateUsage]

_LINES = 1000


def _most_held(text: str, monkeypatch: pytest.MonkeyPatch) -> int:
    held: list[int] = []
    peek = _FlowParser._peek  # pyright: ignore[reportPrivateUsage]

    def counted(parser: _FlowParser) -> str:
        character = peek(parser)
        held.append(parser.held)
        return character

    monkeypatch.setattr(_FlowParser, "_peek", counted)
    yaml.parse(text)
    return max(held)


@pytest.mark.parametrize(
    "line", ["1,", "abc,", "'a b',", '"a",', "[1],", "{a: 1},", "&x 1,"], ids=repr
)
def test_a_flow_sequence_holds_one_line_at_a_time(
    line: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = "[\n" + f"{line}\n" * _LINES + "]"
    assert _most_held(text, monkeypatch) <= len(line) + 1


def test_a_flow_mapping_holds_one_line_at_a_time(monkeypatch: pytest.MonkeyPatch) -> None:
    text = "{\n" + "".join(f"k{i}: v,\n" for i in range(_LINES)) + "}"
    assert _most_held(text, monkeypatch) <= len(f"k{_LINES}: v,") + 1
