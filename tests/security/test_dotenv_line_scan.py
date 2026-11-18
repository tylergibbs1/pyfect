"""(pyfect) Reading a ``.env`` file costs about what its length does, blank lines included.

Every line start is a place a ``NAME=value`` line may begin, and the line pattern first skips
whitespace, line ends included. Tried at each line start of a run of blank lines, it read the
rest of the run each time: 16,000 newlines took 2.6 s. ``test_lines_are_found_as_before``
shows the lines read are the ones ``finditer`` found.
"""

from __future__ import annotations

# pyright: reportPrivateUsage=false
import re
from collections.abc import Callable, Iterator
from itertools import product
from typing import Any

from _growth import cpu_pair
from _guards import guards
from hypothesis import given, settings
from hypothesis import strategies as st

from pyfect import _js
from pyfect.config_provider import _dotenv, from_dot_env_contents

_LINES = 8000


def _spans(found: Iterator[re.Match[str]]) -> list[tuple[tuple[int, int], tuple[str | Any, ...]]]:
    return [(match.span(), match.groups()) for match in found]


def _same_lines(text: str) -> None:
    assert _spans(_dotenv._lines(text)) == _spans(_dotenv._LINE.finditer(text)), repr(text)


def _reading(contents: str) -> Callable[[], object]:
    return lambda: from_dot_env_contents(contents)


@guards("967c6353", "dotenv-blank-runs-rescanned")
def test_blank_lines_before_a_line_without_a_value_cost_about_what_plain_text_does() -> None:
    # The last line is not a NAME=value line, so no line start in the run begins one.
    blank = "\n" * _LINES + "x"
    spaced = " \n" * (_LINES // 2) + "x"
    plain = "A=" + "1" * (_LINES + 1)
    for costly in (blank, spaced):
        slow, fast = cpu_pair(_reading(costly), _reading(plain))
        assert slow <= 20 * max(fast, 0.001), f"{slow * 1000:.1f} ms against {fast * 1000:.1f} ms"


_NEAR_LINES = "A= \n'#x\\"
"""A name, its separator, spaces, line ends, a quote, a comment and an escape."""


def test_every_short_text_reads_the_lines_finditer_found() -> None:
    for length in range(7):
        for chars in product(_NEAR_LINES, repeat=length):
            _same_lines("".join(chars))


@settings(max_examples=1500)
@given(
    st.text(
        st.sampled_from(_NEAR_LINES + '"`:\u2028\t') | st.sampled_from(_js.SPACE[:6]),
        max_size=40,
    )
)
def test_lines_are_found_as_before(text: str) -> None:
    _same_lines(text)
