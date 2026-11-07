import pyfect as fx
from pyfect import metric

requests = metric.counter("http_requests", attributes={"route": "/users"})
latency = metric.timer("http_latency")


def handler() -> fx.Effect[str]:
    return fx.sleep("10 millis").as_("ok")


# track adds 1 per success; track_duration records how long each call took.
tracked = handler().track_duration(latency).track(requests.with_constant_input(1))

fx.run_blocking(fx.for_each(range(3), lambda _: tracked))

text = fx.run_blocking(metric.prometheus_format())
assert 'http_requests{route="/users"} 3' in text
assert "http_latency_count 3" in text
