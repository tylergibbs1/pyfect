"""Threads a test owns, found by the name its code gives them.

Other threads come and go while a test runs (blocking-pool workers exit
after idling, timers end), so a test never counts every thread in the
process: it looks at the threads named by the code under test."""

import threading


def live_threads(name_prefix: str) -> list[threading.Thread]:
    """The threads alive now whose name starts with ``name_prefix``."""
    return [thread for thread in threading.enumerate() if thread.name.startswith(name_prefix)]
