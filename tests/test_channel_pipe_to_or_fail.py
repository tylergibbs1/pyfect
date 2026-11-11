"""``pipe_to_or_fail`` unwraps only the upstream failures it hid.

Upstream failures reach the downstream channel as ``Die(Done(cause))``; a
downstream defect that is a ``Done`` of anything but a cause is the
downstream's own and stays as it is (Effect's ``isUpstreamFailure``).
"""

from typing import Never

import pyfect as fx
from pyfect import channel, testing


@testing.effect
def test_a_downstream_done_defect_that_hides_no_cause_stays_a_defect():
    defect = fx.Done(5)
    downstream: channel.Channel[Never, Never, Never, int] = channel.die(defect)
    ex = yield from channel.from_iterable([1]).pipe_to_or_fail(downstream).run_drain().exit()
    assert ex == fx.exit.die(defect)
