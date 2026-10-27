"""Where ``jittered`` gets its randomness: a float in ``[0, 1)``.

Effect reads its ``Random`` service here. Until pyfect has one, this is
Python's ``random.random``; swapping in the service changes only this
module."""

from __future__ import annotations

import random

from pyfect._core import Effect
from pyfect.effect import sync


def next_double() -> Effect[float]:
    return sync(random.random)
