"""Pull and channel parameters reject a function when called, naming the
parameter. ``tests/test_effect_arguments.py`` walks the whole API but
misses ``ChannelBase``-annotated parameters (``to_transform``,
``transform_pull``, ``scoped``)."""

from collections.abc import Callable
from typing import Any

import pytest

from pyfect import channel, pull


def _function() -> None: ...


# Typed Any: pyright rightly rejects passing a function here.
_not_an_effect: Any = _function


def _identity(p: Any, _scope: Any = None) -> Any:
    return p


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda: channel.to_transform(_not_an_effect), "channel must be a Channel"),
        (lambda: channel.scoped(_not_an_effect), "channel must be a Channel"),
        (lambda: channel.transform_pull(_not_an_effect, _identity), "channel must be a Channel"),
        (lambda: channel.from_pull(_not_an_effect), "make must be an Effect"),
        (lambda: pull.catch_done(_not_an_effect, _identity), "pull must be an Effect"),
        (
            lambda: pull.match_effect(
                _not_an_effect, on_success=_identity, on_failure=_identity, on_done=_identity
            ),
            "pull must be an Effect",
        ),
    ],
    ids=["to_transform", "scoped", "transform_pull", "from_pull", "catch_done", "match_effect"],
)
def test_a_function_is_rejected_naming_the_parameter(call: Callable[[], object], message: str):
    with pytest.raises(TypeError, match=rf"^{message}, got function"):
        call()
