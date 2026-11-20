"""A run in a fork of the snippet server (`_snippet_forks.py`) ends as `python -P` would."""

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from _snippet_forks import Forks

ROOT = Path(__file__).parent.parent

PROGRAMS = {
    "prints": "import sys; print('out'); print('err', file=sys.stderr)",
    "exits": "import sys; print('bye'); sys.exit(3)",
    "raises": "def f():\n    raise ValueError('boom')\nf()",
    "at exit": "import atexit; atexit.register(lambda: print('at exit'))",
    "argv and main": "import sys; print(sys.argv, __name__, sys.path[0] == '')",
    "env": "import os; print(os.environ.get('SNIPPET_FORKS_TEST'))",
    "thread": "import threading, time\n"
    "threading.Thread(target=lambda: (time.sleep(0.2), print('joined'))).start()",
    "pyfect": "import pyfect as fx; print(fx.run_sync(fx.succeed(1)))",
    "subprocess": "import subprocess, sys\n"
    "print(subprocess.run([sys.executable, '-c', 'print(2)'], capture_output=True).stdout)",
}


@pytest.fixture(scope="module")
def forks() -> Iterator[Forks]:
    forks = Forks(ROOT, ["pyfect", "not_a_module_anywhere"])
    yield forks
    forks.close()


@pytest.mark.parametrize("program", PROGRAMS.values(), ids=PROGRAMS.keys())
def test_a_fork_runs_a_program_as_python_does(forks: Forks, program: str):
    env = {"SNIPPET_FORKS_TEST": "set"}
    forked = forks.run("-c", program, "an arg", env=env)
    started = subprocess.run(
        [sys.executable, "-P", "-c", program, "an arg"],
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=ROOT,
        env=os.environ | env,
    )
    # A traceback names the fork server's frames too; its last line is the error.
    assert (forked.returncode, forked.stdout, forked.stderr.splitlines()[-1:]) == (
        started.returncode,
        started.stdout,
        started.stderr.splitlines()[-1:],
    )
    assert ("line 2, in f" in forked.stderr) == ("raise" in program)


def test_a_fork_runs_a_script_as_its_main(forks: Forks, tmp_path: Path):
    script = tmp_path / "script.py"
    script.write_text("import sys\nprint(__name__, __file__ == sys.argv[0], sys.argv[1:])\n")
    done = forks.run(str(script), "x")
    assert (done.returncode, done.stdout) == (0, "__main__ True ['x']\n")
