"""pyfect writes years without ``strftime``.

glibc's ``strftime("%Y")`` gave year 999 as ``999``, not ``0999``, on Python 3.13, so on Linux
a ``DateTime.Utc`` before year 1000 encoded to a string that did not decode. ISO strings come
from ``pyfect._js.to_iso_string``.
"""

import re
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "pyfect"


def test_no_strftime_writes_a_year():
    found = [
        f"{path.relative_to(SRC)}:{number}"
        for path in SRC.rglob("*.py")
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\.strftime\(.*%[YGCy]", line)
    ]
    assert found == []
