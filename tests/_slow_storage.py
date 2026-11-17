"""Runs a snippet as `_count_sleeps.py` does, with every commit to an SQLite file taking
10 ms longer, as a slow disk's fsync makes it (`python _slow_storage.py file.py`).

In CI, cluster/drain.py once completed 7.3 s of live-clock sleep where it takes 1.1 s on an
idle machine: a stopping runner releases each of its 300 shards in its own commit, and the
runner's poll loops keep sleeping for as long as that takes. In-memory databases are not
slowed: they never wait for a disk.
"""

import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

COMMIT_DELAY = 0.01

_connect = sqlite3.connect


class SlowCommits(sqlite3.Connection):
    """With `isolation_level=None`, a write that changes rows outside a transaction commits
    at once, and so does `COMMIT`; each then waits on the connection's thread, as fsync would."""

    delayed = 0
    """How many commits waited."""

    def execute(self, sql: str, *args: Any) -> sqlite3.Cursor:
        changes = self.total_changes
        cursor = super().execute(sql, *args)
        ends = sql.lstrip()[:6].upper() in ("COMMIT", "END")
        if not self.in_transaction and (ends or self.total_changes != changes):
            self.delayed += 1
            time.sleep(COMMIT_DELAY)
        return cursor


def _in_memory(database: object) -> bool:
    name = str(database)
    return name in ("", ":memory:") or "mode=memory" in name


def slow_connect(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
    if not _in_memory(database):
        kwargs.setdefault("factory", SlowCommits)
    return _connect(database, *args, **kwargs)


if __name__ == "__main__":
    sqlite3.connect = slow_connect
    sys.path.insert(0, str(Path(__file__).parent))  # -P leaves this directory off
    from _count_sleeps import main

    main()
