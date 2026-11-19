"""CPython's re-run of the main script inside a subinterpreter.

To unpickle a function of ``__main__`` (one that reads globals, so it crosses by
reference), a subinterpreter runs the main script again with ``runpy``, as a
module named ``<fake __main__>``. A script without an ``if __name__ ==
"__main__":`` guard reaches its own ``fx.run_*`` there, which would run the whole
program again inside the subinterpreter. ``refuse_run`` makes that run raise
instead, and ``take_refused`` tells the pool's worker it happened (CPython drops
the re-run's exception and reports only that the function could not cross).
"""

import sys

FAKE_MAIN = "<fake __main__>"
"""The name CPython runs the re-run under; ``runpy`` keeps it in ``sys.modules``
only while the re-run executes."""

_refused = [False]


class MainScriptRerunError(RuntimeError):
    """A function defined in the script you ran (``__main__``) was sent to a
    subinterpreter, which re-ran the script to find it, and the script's
    top-level code started a pyfect run there."""


def refuse_run() -> None:
    """Raise ``MainScriptRerunError`` when called during CPython's re-run of
    the main script."""
    if FAKE_MAIN in sys.modules:
        _refused[0] = True
        raise MainScriptRerunError(
            "the main script started a pyfect run while a subinterpreter re-ran it as "
            f"{FAKE_MAIN!r} to find a function of it"
        )


def take_refused() -> bool:
    """Whether a run was refused in this interpreter since the last call."""
    refused, _refused[0] = _refused[0], False
    return refused
