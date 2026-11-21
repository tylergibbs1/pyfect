"""``dump_stacks_then_kill``, the hang killer that replaced ``dump_traceback_later(exit=True)``:
a hung process writes each thread's own stack and is then killed."""

import subprocess
import sys
from pathlib import Path

import pytest
from _subprocess import SUBPROCESS_TIMEOUT
from _thread_cpu_timer import AVAILABLE

HUNG = """
import sys
import threading

sys.path.insert(0, {tests!r})
import _thread_cpu_timer

def parked_on_purpose():
    threading.Event().wait()

threading.Thread(target=parked_on_purpose, daemon=True).start()
_thread_cpu_timer.dump_stacks_then_kill(0.5, refresh={refresh})
threading.Event().wait()  # hung on the main thread
"""


@pytest.mark.skipif(
    not AVAILABLE, reason="off Linux no timer signals one thread, so only the kill is left"
)
@pytest.mark.parametrize("refresh", [False, True])
def test_a_hung_process_writes_each_threads_stack_and_is_killed(refresh: bool) -> None:
    source = HUNG.format(tests=str(Path(__file__).parent), refresh=refresh)
    done = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT,
        check=False,
    )
    assert done.returncode == -9, done.stderr
    assert done.stderr.count("Stack (most recent call first):") >= 2, done.stderr
    assert "in parked_on_purpose" in done.stderr
    hang = 1 + source.splitlines().index("threading.Event().wait()  # hung on the main thread")
    assert f'File "<string>", line {hang} in <module>' in done.stderr
