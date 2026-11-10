"""``_cluster_abandon.interrupt`` keeps its ``Abandon`` annotation when an
interrupt is already pending on an uninterruptible fiber (Effect 4.1.2's
``internal/clusterAbandon``: annotate before opening the interruptible
region)."""

from __future__ import annotations

from typing import Never

import pyfect as fx
from pyfect import exit as Exit
from pyfect import testing
from pyfect.cluster import _cluster_abandon
from pyfect.deferred import Deferred


@testing.effect
def test_abandon_annotates_an_interrupt_already_pending():
    started = Deferred[None, Never]()
    release = Deferred[None, Never]()

    @fx.gen
    def body():
        # Uninterruptible until it abandons, so the outside interrupt stays pending.
        work = (
            started.succeed(None)
            .and_then(release.wait())
            .and_then(_cluster_abandon.interrupt)
            .uninterruptible()
        )
        fiber = yield from work.fork()
        yield from started.wait()
        interrupting = yield from fiber.interrupt().fork()
        yield from release.succeed(None)
        yield from interrupting.join()
        exit = yield from fiber.await_exit()
        assert isinstance(exit, Exit.Failure)
        assert _cluster_abandon.is_cause(exit.cause)

    yield from body
