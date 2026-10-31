"""``runner_health``: every runner alive (noop), alive when it answers a
ping, or when its Kubernetes pod is ready or still initializing."""

from __future__ import annotations

import json
from typing import Any, cast

import pyfect as fx
from pyfect import testing
from pyfect.cluster import k8s_http_client as K8s
from pyfect.cluster import runner_health
from pyfect.cluster.cluster_error import RunnerUnavailable
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.runner_health import RunnerHealth
from pyfect.cluster.runners import Runners, RunnersService
from pyfect.effect import Effect
from pyfect.file_system import FileSystem, NoopFileSystem
from pyfect.http import client, response
from pyfect.http.request import HttpClientRequest

_ADDRESS = RunnerAddress(host="10.0.0.1", port=34431)


class _Pinged:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.pings = 0

    def ping(self, address: RunnerAddress) -> Effect[None, RunnerUnavailable]:
        def run() -> Effect[None, RunnerUnavailable]:
            self.pings += 1
            if self.pings <= self.failures:
                return fx.fail(RunnerUnavailable(address=address))
            return fx.void

        return fx.suspend(run)


def _is_alive_by_ping(runners: _Pinged) -> Effect[bool]:
    @fx.gen
    def body():
        health = yield from RunnerHealth()
        alive = yield from health.is_alive(_ADDRESS).fork()
        yield from testing.adjust(10)
        return (yield from alive.join())

    return body.pipe(fx.provide(runner_health.layer_ping)).pipe(
        fx.provide_service(Runners, cast("RunnersService", runners))
    )


@testing.effect
def test_noop_says_every_runner_is_alive():
    @fx.gen
    def body():
        health = yield from RunnerHealth()
        return (yield from health.is_alive(_ADDRESS))

    assert (yield from body.pipe(fx.provide(runner_health.layer_noop))) is True


@testing.effect
def test_ping_retries_five_times_before_giving_up():
    recovers = _Pinged(failures=5)
    assert (yield from _is_alive_by_ping(recovers)) is True
    assert recovers.pings == 6
    dead = _Pinged(failures=6)
    assert (yield from _is_alive_by_ping(dead)) is False
    assert dead.pings == 6


def _pod(ip: str, ready: str) -> dict[str, Any]:
    return {
        "status": {
            "phase": "Running",
            "podIP": ip,
            "hostIP": "10.0.1.1",
            "conditions": [
                {"type": "Initialized", "status": "True", "lastTransitionTime": "t0"},
                {"type": "Ready", "status": ready, "lastTransitionTime": "t1"},
            ],
        }
    }


def _is_alive_by_k8s(address: RunnerAddress, status: int, pods: list[dict[str, Any]]):
    urls: list[tuple[str, list[tuple[str, str]]]] = []

    def handle(request: HttpClientRequest) -> Effect[Any]:
        def run() -> Any:
            urls.append((request.url, [(k, str(v)) for k, v in request.url_params]))
            return response.make(request, json.dumps({"items": pods}), status=status)

        return fx.sync(run)

    @fx.gen
    def body():
        health = yield from RunnerHealth()
        return (yield from health.is_alive(address))

    layer = runner_health.layer_k8s(namespace="cluster", label_selector="app=runner")
    alive = yield from (
        body.pipe(fx.provide(layer))
        .pipe(fx.provide(K8s.layer))
        .pipe(fx.provide_service(FileSystem, NoopFileSystem()))
        .pipe(fx.provide(client.layer_test(handle)))
    )
    return alive, urls


@testing.effect
def test_k8s_reads_the_pod_at_the_runner_host():
    pods = [_pod("10.0.0.1", "True"), _pod("10.0.0.2", "False")]
    alive, urls = yield from _is_alive_by_k8s(_ADDRESS, 200, pods)
    assert alive is True
    assert urls == [
        (
            "https://kubernetes.default.svc/api/v1/namespaces/cluster/pods",
            [("fieldSelector", "status.phase=Running"), ("labelSelector", "app=runner")],
        )
    ]
    not_ready, _ = yield from _is_alive_by_k8s(RunnerAddress(host="10.0.0.2", port=1), 200, pods)
    assert not_ready is False
    missing, _ = yield from _is_alive_by_k8s(RunnerAddress(host="10.0.0.9", port=1), 200, pods)
    assert missing is False


@testing.effect
def test_k8s_counts_a_runner_alive_when_the_api_fails():
    alive, _ = yield from _is_alive_by_k8s(_ADDRESS, 403, [])
    assert alive is True
