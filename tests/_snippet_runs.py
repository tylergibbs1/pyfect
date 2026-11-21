"""A docs snippet's run as its test waits for it (``tests/test_doc_snippets.py``): first for the
start of the shared server the snippet needs, outside the test's hang alarm, then for the run,
under it. A start waits on its own deadlines and fails with the container's state and logs
(``oracle/_shared_server.py``); counted in the alarm, a slow ``docker run`` failed the snippet
that happened to wait for it as hung."""

from concurrent.futures import Future
from dataclasses import dataclass

import _timeout


@dataclass(frozen=True)
class Run[T]:
    server: Future[object] | None
    """The start of the shared server the snippet needs, if any."""
    done: Future[T]

    def result(self) -> T:
        if self.server is not None:
            with _timeout.suspended():
                self.server.result()
        return self.done.result()
