"""Ports of Effect's ``test/cluster/K8sHttpClient.test.ts`` for
``pyfect.cluster.k8s_http_client``, through a test ``HttpClient`` and a
no-op file system (never a real cluster). Each test's docstring is the
Effect test title."""

from __future__ import annotations

import json
from typing import Any

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.cluster import k8s_http_client as K8s
from pyfect.file_system import FileSystem, NoopFileSystem
from pyfect.http import client, response
from pyfect.http.body import Bytes
from pyfect.http.request import HttpClientRequest


class _TokenFile(NoopFileSystem):
    def __init__(self) -> None:
        self.token = "token-1"

    def read_file_string(self, path: str, encoding: str = "utf-8"):
        return fx.sync(lambda: self.token)


@testing.effect
def test_uses_the_rotated_token_after_the_token_cache_expires():
    """uses the rotated token after the token cache expires"""
    files = _TokenFile()
    authorization: list[str | None] = []
    urls: list[str] = []

    def handle(request: HttpClientRequest) -> fx.Effect[Any]:
        def run() -> Any:
            authorization.append(request.headers.get("authorization"))
            urls.append(request.url)
            return response.make(request, status=200)

        return fx.sync(run)

    def body():
        k8s = yield from K8s.K8sHttpClient()
        request = k8s.get("/v1/pods")
        yield from request
        files.token = "token-2"
        yield from testing.adjust("61 seconds")
        yield from request
        assert authorization == ["Bearer token-1", "Bearer token-2"]
        assert urls == ["https://kubernetes.default.svc/api/v1/pods"] * 2

    yield from (
        fx.gen(body)
        .pipe(fx.provide(K8s.layer))
        .pipe(fx.provide_service(FileSystem, files))
        .pipe(fx.provide(client.layer_test(handle)))
    )


@testing.effect
def test_decodes_null_condition_last_transition_time_values():
    """Pod / decodes null condition lastTransitionTime values"""
    pod = yield from S.decode_unknown_effect(K8s.POD)(
        {
            "status": {
                "phase": "Running",
                "podIP": "10.0.0.1",
                "hostIP": "10.0.0.2",
                "conditions": [
                    {"type": "Initialized", "status": "True", "lastTransitionTime": None},
                    {"type": "Ready", "status": "False", "lastTransitionTime": None},
                ],
            }
        }
    )
    assert pod.status.conditions[0].last_transition_time is None
    assert pod.is_ready is False
    assert pod.is_ready_or_initializing is True


def _pod_json(ip: str, ready: str) -> dict[str, Any]:
    return {
        "status": {
            "phase": "Running",
            "podIP": ip,
            "hostIP": "10.0.0.254",
            "conditions": [{"type": "Ready", "status": ready, "lastTransitionTime": None}],
        }
    }


def _provide(effect: fx.Effect[Any, Any, Any], handle: Any) -> fx.Effect[Any, Any, Any]:
    return (
        effect.pipe(fx.provide(K8s.layer))
        .pipe(fx.provide_service(FileSystem, _TokenFile()))
        .pipe(fx.provide(client.layer_test(handle)))
    )


@testing.effect
def test_get_pods_lists_running_pods_by_ip():
    """(pyfect) makeGetPods lists running pods by IP, filtered by namespace and labels"""
    requests: list[HttpClientRequest] = []

    def handle(request: HttpClientRequest) -> fx.Effect[Any]:
        requests.append(request)
        items = {"items": [_pod_json("10.0.0.1", "True"), _pod_json("10.0.0.2", "False")]}
        return fx.succeed(response.make(request, json.dumps(items)))

    def body():
        get_pods = yield from K8s.make_get_pods(namespace="ns", label_selector="app=cluster")
        pods = yield from get_pods
        assert sorted(pods) == ["10.0.0.1", "10.0.0.2"]
        assert pods["10.0.0.1"].is_ready
        assert not pods["10.0.0.2"].is_ready
        yield from get_pods  # cached
        assert len(requests) == 1
        url = requests[0].url
        assert url == "https://kubernetes.default.svc/api/v1/namespaces/ns/pods"
        assert requests[0].url_params.get_first("fieldSelector") == "status.phase=Running"
        assert requests[0].url_params.get_first("labelSelector") == "app=cluster"

    yield from _provide(fx.gen(body), handle)


@testing.effect
def test_create_pod_waits_until_ready_and_deletes_on_close():
    """(pyfect) makeCreatePod waits until the pod is ready and deletes it with the scope"""
    calls: list[str] = []
    posted: list[Any] = []
    state = {"exists": False, "reads": 0}

    def handle(request: HttpClientRequest) -> fx.Effect[Any]:
        calls.append(f"{request.method} {request.url.removeprefix(K8s.API_URL)}")
        if request.method == "POST":
            assert isinstance(request.body, Bytes)
            posted.append(json.loads(request.body.body))
            state["exists"] = True
            return fx.succeed(response.make(request, "{}", status=201))
        if request.method == "DELETE":
            state["exists"] = False
            return fx.succeed(response.make(request, "{}"))
        if not state["exists"]:
            return fx.succeed(response.make(request, "{}", status=404))
        state["reads"] += 1
        ready = "True" if state["reads"] >= 2 else "False"
        return fx.succeed(response.make(request, json.dumps(_pod_json("10.0.0.9", ready))))

    def body():
        create = yield from K8s.make_create_pod
        scope = fx.CloseableScope()
        fiber = (
            yield from create({"metadata": {"name": "p1"}})
            .pipe(fx.provide_service(fx.Scope, scope))
            .fork()
        )
        for _ in range(3):
            yield from testing.adjust("3 seconds")
        status = yield from fiber.join()
        assert status.pod_ip == "10.0.0.9"
        # Effect spreads the spec last, so its metadata replaces the defaulted one
        assert posted == [{"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "p1"}}]
        assert calls == [
            "POST /v1/namespaces/default/pods",
            "GET /v1/namespaces/default/pods/p1",
            "GET /v1/namespaces/default/pods/p1",
        ]
        yield from scope.close(fx.exit.succeed(None))
        assert calls[3:] == [
            "DELETE /v1/namespaces/default/pods/p1",
            "GET /v1/namespaces/default/pods/p1",
        ]

    yield from _provide(fx.gen(body), handle)


def test_is_ready_or_initializing_tells_null_from_absent_transition_times():
    """(pyfect) Pod.isReadyOrInitializing: a null lastTransitionTime is not
    a missing condition (values printed by Effect under Node)"""

    def pod(*conditions: dict[str, Any]) -> K8s.Pod:
        status = {"phase": "Running", "podIP": "a", "hostIP": "b", "conditions": list(conditions)}
        return S.decode_unknown_sync(K8s.POD)({"status": status})

    initialized = {"type": "Initialized", "status": "True", "lastTransitionTime": None}
    not_ready = {"type": "Ready", "status": "False", "lastTransitionTime": None}
    assert pod(initialized).is_ready_or_initializing is False
    assert pod(not_ready).is_ready_or_initializing is False
    assert pod().is_ready_or_initializing is True
