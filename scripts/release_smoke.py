"""Smoke test for a built distribution, run by the release workflow.

Run it outside the project with only the built wheel or sdist installed:
    uv run --isolated --no-project --with dist/<file> scripts/release_smoke.py <version>
"""

import sys
from importlib.metadata import version

import pyfect as fx

expected = sys.argv[1]
installed = version("pyfect-dev")
if installed != expected:
    sys.exit(f"installed pyfect-dev {installed}, expected {expected}")
if fx.run_sync(fx.succeed(1).map(lambda n: n + 1)) != 2:
    sys.exit("run_sync gave the wrong result")
print(f"pyfect-dev {installed} imports and runs")
