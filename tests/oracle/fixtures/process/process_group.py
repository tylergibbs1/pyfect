"""Effect's ``process-group.ts`` fixture, in Python.

The leader and descendant share a process group and inherited stdio. The
leader exits at once on SIGTERM unless a delay is given. The descendant
exits after its delay (200ms by default) or ignores SIGTERM and writes
heartbeats.

    process_group.py leader|descendant MODE MARKER [LEADER_DELAY] [DESCENDANT_DELAY]
"""

import os
import signal
import subprocess
import sys
import threading
import time
from types import FrameType


def _exit_after(seconds: float, write_marker: str | None = None) -> None:
    def run() -> None:
        time.sleep(seconds)
        if write_marker is not None:
            with open(write_marker, "w") as f:
                f.write("exited")
        os._exit(0)

    threading.Thread(target=run, daemon=True).start()


def leader(mode: str, marker: str, leader_delay: str, descendant_delay: str) -> None:
    subprocess.Popen(
        [sys.executable, __file__, "descendant", mode, marker, leader_delay, descendant_delay],
        stdin=subprocess.DEVNULL,
    )
    delay = float(leader_delay) / 1000
    if delay > 0:

        def on_term(_signum: int, _frame: FrameType | None) -> None:
            _exit_after(delay)

        signal.signal(signal.SIGTERM, on_term)
    data = os.read(0, 1024)
    if data:
        sys.exit(1 if data.decode().strip() == "exit 1" else 0)
    while True:
        time.sleep(1)


def descendant(mode: str, marker: str, descendant_delay: float) -> None:
    if mode == "exit-on-signal":

        def on_term(_signum: int, _frame: FrameType | None) -> None:
            _exit_after(descendant_delay, marker)

        signal.signal(signal.SIGTERM, on_term)
    else:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)

        def heartbeat() -> None:
            while True:
                with open(marker, "a") as f:
                    f.write("x")
                time.sleep(0.01)

        threading.Thread(target=heartbeat, daemon=True).start()
    sys.stdout.write(f"READY {os.getpid()}\n")
    sys.stdout.flush()
    time.sleep(5)
    os._exit(1)


def main() -> None:
    role, mode, marker = sys.argv[1:4]
    leader_delay = sys.argv[4] if len(sys.argv) > 4 else "0"
    descendant_delay = sys.argv[5] if len(sys.argv) > 5 else "200"
    if role == "leader":
        leader(mode, marker, leader_delay, descendant_delay)
    else:
        descendant(mode, marker, float(descendant_delay) / 1000)


if __name__ == "__main__":
    main()
