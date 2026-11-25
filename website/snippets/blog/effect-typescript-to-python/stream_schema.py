from typing import assert_type

import pyfect as fx
from pyfect import schema as S
from pyfect import stream


# Schema.Class<Reading>("Reading")({ sensor: Schema.String, celsius: Schema.Number })
class Reading(S.Class):
    sensor: str
    celsius: float


decode = S.decode_unknown_effect(S.from_json_string(Reading))

lines = ['{"sensor": "a", "celsius": 21.5}', '{"sensor": "b", "celsius": 19}']

# Stream.fromIterable(lines).pipe(Stream.mapEffect(decode, { concurrency: 2 }))
# becomes method calls: only combinators that remove a type are functions for .pipe.
readings = stream.from_iterable(lines).map_effect(decode, concurrency=2)
assert_type(readings, stream.Stream[Reading, S.SchemaError])

collected = fx.run_blocking_exit(readings.map(lambda r: f"{r.sensor}: {r.celsius}").run_collect())
print(collected)
