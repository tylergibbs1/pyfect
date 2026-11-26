import json
from dataclasses import dataclass
from typing import assert_type

import pyfect as fx


@dataclass
class BadConfig(fx.TaggedError):
    detail: str


def parse_config(text: str) -> fx.Effect[dict[str, object], BadConfig]:
    # try_ turns the exception you expect into a typed failure.
    return fx.try_(lambda: json.loads(text), catch=lambda e: BadConfig(str(e)))


port = parse_config('{"port": 8080}').map(lambda config: config["port"])
assert_type(port, fx.Effect[object, BadConfig])
print(fx.run_blocking(port.catch_all(lambda e: fx.succeed(f"bad config: {e.detail}"))))

broken = parse_config("{port: 8080}").map(lambda config: config["port"])
print(fx.run_blocking(broken.catch_all(lambda e: fx.succeed(f"bad config: {e.detail}"))))
