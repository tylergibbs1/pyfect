"""Whether a runner is alive (Effect's ``RunnerHealth``). Sharding keeps
the shards of a live runner where they are, and moves those of a dead
one: ``layer_noop`` says every runner is alive, ``layer_ping`` pings it
through ``Runners``, and ``layer_k8s`` reads its pod's readiness."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Never

from pyfect import layer as layer_
from pyfect._core import Effect
from pyfect.cluster.k8s_http_client import K8sHttpClient, Pod, make_get_pods
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.runners import Runners, RunnersService
from pyfect.context import Tag
from pyfect.effect import succeed
from pyfect.exit import is_success
from pyfect.layer import Layer
from pyfect.schedule import spaced


@dataclass(frozen=True, slots=True)
class RunnerHealthService:
    is_alive: Callable[[RunnerAddress], Effect[bool]]


class RunnerHealth(Tag[RunnerHealthService], key="effect/cluster/RunnerHealth"):
    """How this runner checks whether another is alive."""


def _alive(_: RunnerAddress) -> Effect[bool]:
    return succeed(True)


layer_noop: Layer[RunnerHealth] = layer_.succeed(RunnerHealth, RunnerHealthService(_alive))
"""Every runner is alive (for tests and local development)."""

_PING_SCHEDULE = spaced("500 millis")


def _make_ping(runners: RunnersService) -> RunnerHealthService:
    def is_alive(address: RunnerAddress) -> Effect[bool]:
        pinged = runners.ping(address).timeout("10 seconds").retry(times=5, schedule=_PING_SCHEDULE)
        return pinged.exit().map(is_success)

    return RunnerHealthService(is_alive)


make_ping: Effect[RunnerHealthService, Never, Runners] = Runners().map(_make_ping)
"""Alive when a ping answers within ten seconds, retried five times half
a second apart."""

layer_ping: Layer[RunnerHealth, Never, Runners] = layer_.effect(RunnerHealth, make_ping)
"""``RunnerHealth`` from ``make_ping``: alive when a ping answers."""


def make_k8s(
    *, namespace: str | None = None, label_selector: str | None = None
) -> Effect[RunnerHealthService, Never, K8sHttpClient]:
    """Alive when the pod at the runner's host is ready or initializing;
    alive too when the Kubernetes API cannot be read."""

    def service(pods: Effect[dict[str, Pod], object]) -> RunnerHealthService:
        def is_alive(address: RunnerAddress) -> Effect[bool]:
            def ready(by_ip: dict[str, Pod]) -> bool:
                pod = by_ip.get(address.host)
                return pod is not None and pod.is_ready_or_initializing

            return pods.map(ready).catch_cause(lambda _: succeed(True))

        return RunnerHealthService(is_alive)

    return make_get_pods(namespace=namespace, label_selector=label_selector).map(service)


def layer_k8s(
    *, namespace: str | None = None, label_selector: str | None = None
) -> Layer[RunnerHealth, Never, K8sHttpClient]:
    """``make_k8s`` as a layer. The ``HttpClient`` must trust the pod CA
    and the service account must be allowed to list pods."""
    return layer_.effect(RunnerHealth, make_k8s(namespace=namespace, label_selector=label_selector))


__all__ = [
    "RunnerHealth",
    "RunnerHealthService",
    "layer_k8s",
    "layer_noop",
    "layer_ping",
    "make_k8s",
    "make_ping",
]
