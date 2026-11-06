from dataclasses import dataclass

import pyfect as fx
from pyfect import testing


@dataclass
class Rejected(fx.TaggedError):
    by: str


def decide() -> fx.Effect[None, Rejected]:
    return fx.fail(Rejected("grace")).with_span("decide")


def test_decide_rejects():
    exit_ = fx.run_blocking_exit(decide())
    # The failure records the span it happened in, so exit_ != fx.exit.fail(Rejected("grace")).
    testing.assert_exit_fail(exit_, Rejected("grace"))
