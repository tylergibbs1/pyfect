"""One side of ``compare.py``: ``python _measure.py SRC CASE...`` prints each case's time
over the gate's calibration as JSON, with pyfect imported from ``SRC``."""

import json
import sys
from pathlib import Path

from gate import calibrate
from streams import CASES, best_of

import pyfect


def main() -> None:
    src, names = Path(sys.argv[1]).resolve(), sys.argv[2:]
    # PYTHONPATH must win over the installed package, or both sides measure one tree.
    assert Path(pyfect.__file__).resolve().is_relative_to(src), pyfect.__file__
    runs = {name: run for name, _, run in CASES}
    calibration = best_of(calibrate)
    print(json.dumps({name: best_of(runs[name]) / calibration for name in names}))


if __name__ == "__main__":
    main()
