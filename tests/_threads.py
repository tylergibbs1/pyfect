"""Threads a test owns, found by the name its code gives them.

Other threads come and go while a test runs (blocking-pool workers exit
after idling, timers end), so a test never counts every thread in the
process: it looks at the threads named by the code under test."""

import threading


def live_threads(name_prefix: str) -> list[threading.Thread]:
    """The threads alive now whose name starts with ``name_prefix``."""
    return [thread for thread in threading.enumerate() if thread.name.startswith(name_prefix)]


PROCESS_WIDE = "process-wide "


def process_wide(name: str) -> str:
    """The name for a thread meant to run as long as the process: a test peer started on first
    use and shared by every test after. The leaked-thread check (``_leaked_threads``) skips
    threads so named; any other thread a test leaves running is reported."""
    return PROCESS_WIDE + name
