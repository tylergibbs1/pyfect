"""pyright explains a wrong ``@fx.fn`` body against the body parameter.

``fn`` has a ``fn(name: str)`` overload for ``@fx.fn("name")``. When no overload matches a
single argument, pyright reports the last overload it tried; with ``name`` last, an
``async def`` body or a ``def`` with no ``yield`` was reported as "cannot be assigned to
parameter "name" of type "str"", which says nothing about the mistake. The ``name`` overload
now comes first (``tests/test_fn_overloads.py`` generates the order), so the message is about
the generator body. ``tests/type_checks.py`` pins that both bodies are still errors.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SOURCE = """\
import pyfect as fx


@fx.fn
async def coroutine_body(url: str):
    return url


@fx.fn
def no_yield_body():
    return fx.succeed(1)
"""


def test_a_wrong_fn_body_is_explained_against_the_body_parameter(tmp_path: Path) -> None:
    # Outside tests/, which guards running alongside read file by file
    probe = tmp_path / "fn_pyright_probe.py"
    probe.write_text(SOURCE)
    run = subprocess.run(
        [sys.executable, "-m", "pyright", "--outputjson", str(probe)],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    diagnostics = json.loads(run.stdout)["generalDiagnostics"]
    argument = [d["message"] for d in diagnostics if d.get("rule") == "reportArgumentType"]
    assert len(argument) == 2, diagnostics
    for message in argument:
        assert 'parameter "name"' not in message
        assert 'parameter "f"' in message
        assert "Generator[" in message
