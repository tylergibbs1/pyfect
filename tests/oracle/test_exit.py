"""Ports of Effect's ``Exit.test.ts``.

Omitted: ``uses reasons in failed runtime JSON and Node inspection`` and
``toString`` (JSON, Node inspection and JS ``toString`` have no Python
counterpart; the dataclass ``repr`` is Python's form).
"""

from pyfect.cause import Cause, Die, Fail, Interrupt
from pyfect.exit import Exit, Failure


def test_error_mapping_keeps_defects_and_interrupts() -> None:
    """error mapping keeps defects and interrupts"""
    defect = RuntimeError("boom")
    ex: Exit[int, str] = Failure(Cause((Fail("error"), Interrupt(1), Die(defect))))

    def on_failure(_: str) -> str:
        return "mapped"

    expected = Failure(Cause((Fail("mapped"), Interrupt(1), Die(defect))))
    assert ex.map_error(on_failure) == expected
    assert ex.map_both(on_failure=on_failure, on_success=lambda a: a) == expected
