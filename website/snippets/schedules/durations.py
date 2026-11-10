from datetime import timedelta

import pyfect as fx
from pyfect import duration
from pyfect.duration import millis, nanos, seconds

# Every input form parses once, at the boundary, into a Duration.
assert duration.from_input_unsafe("90 seconds") == duration.from_input_unsafe({"minutes": 1.5})
assert duration.from_input_unsafe(timedelta(milliseconds=250)) == millis(250)
assert duration.from_input("ten seconds") is None

# Durations are exact: whole nanoseconds, past what a float can count.
big = nanos(2**53) + nanos(1)
print(big.to_nanos(), big.format_iso())

# Arithmetic and comparisons stay in Durations; units come out at the edge.
total = seconds(1.5) + millis(250)
print(total.format(), total.to_millis(), total > seconds(1))
print(duration.infinity.format(), (duration.infinity - seconds(1)).is_finite())

took, _ = fx.run_blocking(fx.sleep("20 millis").timed())
print(took >= millis(20))
