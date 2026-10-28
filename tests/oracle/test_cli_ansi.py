"""Effect's ``test/cli/Ansi.test.ts``."""

from pyfect.cli._ansi import cursor_to


def test_emits_a_standard_csi_horizontal_absolute_sequence():
    """emits a standard CSI horizontal absolute sequence"""
    assert cursor_to(0) == "\x1b[1G"


def test_emits_a_standard_csi_cursor_position_sequence():
    """emits a standard CSI cursor-position sequence"""
    assert cursor_to(2, 3) == "\x1b[4;3H"
