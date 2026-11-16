"""One side of ``compare.py``: ``python _measure.py SRC CASE...`` prints each case's best
time in seconds as JSON, with pyfect imported from ``SRC``.

The times are raw: both sides run back to back on one runner, so a calibration has nothing
to cancel, and its own swing between processes (25% in noise run 43854358958) moved every
case of a process at once."""

import json
import sys
from pathlib import Path

from streams import CASES, best_of

import pyfect


def main() -> None:
    src, names = Path(sys.argv[1]).resolve(), sys.argv[2:]
    # PYTHONPATH must win over the installed package, or both sides measure one tree.
    assert Path(pyfect.__file__).resolve().is_relative_to(src), pyfect.__file__
    runs = {name: run for name, _, run in CASES}
    print(json.dumps({name: best_of(runs[name]) for name in names}))


if __name__ == "__main__":
    main()
