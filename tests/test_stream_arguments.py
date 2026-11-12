"""Stream constructors over pulls reject a function when called, naming the
parameter."""

from collections.abc import Callable
from typing import Any

import pytest

from pyfect import stream


def _function() -> None: ...


# Typed Any: pyright rightly rejects passing a function here.
_not_an_effect: Any = _function


def _identity(p: Any, *_: Any) -> Any:
    return p


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda: stream.from_pull(_not_an_effect), "make must be an Effect"),
        (lambda: stream.transform_pull(_not_an_effect, _identity), "stream must be a Stream"),
        (
            lambda: stream.transform_pull_bracket(_not_an_effect, _identity),
            "stream must be a Stream",
        ),
    ],
    ids=["from_pull", "transform_pull", "transform_pull_bracket"],
)
def test_a_function_is_rejected_naming_the_parameter(call: Callable[[], object], message: str):
    with pytest.raises(TypeError, match=rf"^{message}, got function"):
        call()
