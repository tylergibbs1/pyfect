"""Numbers as JavaScript's ``String(number)`` writes them, for ``dump`` and
the Prometheus text: ``2`` not ``2.0``, ``1e+21``, ``1.5e-7``."""

from __future__ import annotations

import math
from decimal import Decimal


def js_number(value: float) -> str:
    """``value`` as JavaScript prints it. An ``int`` (Effect's ``bigint``)
    prints in full."""
    if isinstance(value, int):
        return str(value)
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value == 0.0:
        return "0"
    sign = "-" if value < 0 else ""
    # repr is the shortest round-tripping decimal, as JavaScript's.
    exact = Decimal(repr(abs(value))).normalize().as_tuple()
    digits = "".join(map(str, exact.digits))
    k = len(digits)
    n = k + int(exact.exponent)  # value = 0.digits * 10**n
    if k <= n <= 21:
        body = digits + "0" * (n - k)
    elif 0 < n <= 21:
        body = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * -n + digits
    else:
        mantissa = digits[0] + ("." + digits[1:] if k > 1 else "")
        body = f"{mantissa}e{'+' if n - 1 >= 0 else '-'}{abs(n - 1)}"
    return sign + body
