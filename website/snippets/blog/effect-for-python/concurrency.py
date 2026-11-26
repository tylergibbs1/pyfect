from dataclasses import dataclass

import pyfect as fx

interrupted: list[str] = []


@dataclass
class Unavailable(fx.TaggedError):
    region: str


def fetch_price(region: str, millis: int) -> fx.Effect[int, Unavailable]:
    if region == "ap":
        return fx.sleep(f"{millis} millis").and_then(fx.fail(Unavailable(region)))
    record = fx.sync(lambda: interrupted.append(region))
    return fx.sleep(f"{millis} millis").as_(100).on_interrupt(record)


# Three requests at once. When "ap" fails, all interrupts the other two and waits for
# their cleanup before it fails: nothing is left running.
prices = fx.all(
    fetch_price("eu", 1000),
    fetch_price("us", 1000),
    fetch_price("ap", 10),
    concurrency="unbounded",
)
report = prices.pipe(fx.catch_tag(Unavailable, lambda e: fx.succeed(f"{e.region} is down")))

took, result = fx.run_blocking(report.timed())
print(f"result: {result}, interrupted: {sorted(interrupted)}")
assert result == "ap is down" and sorted(interrupted) == ["eu", "us"]
assert took < fx.duration.seconds(1)  # the two slow requests did not run to the end
