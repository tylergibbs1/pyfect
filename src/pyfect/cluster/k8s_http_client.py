"""The Kubernetes API from inside a cluster (Effect's ``K8sHttpClient``).

``layer`` builds a ``K8sHttpClient`` on the shared ``HttpClient``: requests
go to ``https://kubernetes.default.svc/api`` with the mounted
service-account token (re-read at most once a minute, so a rotated token
is picked up), non-2xx statuses fail and transient failures retry every
five seconds. ``make_get_pods`` lists running pods by IP; ``make_create_pod``
creates a pod for the life of a scope and waits until it is ready.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Any, Never

from pyfect import layer as layer_
from pyfect import schedule
from pyfect import schema as S
from pyfect._core import Effect
from pyfect._js import or_default
from pyfect._wire_codec import key, wire_codec
from pyfect.clock import sleep
from pyfect.cluster.k8s_types import Pod as K8sPod
from pyfect.context import Tag
from pyfect.effect import gen, succeed, void
from pyfect.file_system import FileSystem
from pyfect.http import request as request_
from pyfect.http import response as response_
from pyfect.http.client import HttpClient, HttpClientService
from pyfect.http.error import HttpClientError, StatusCodeError
from pyfect.http.request import HttpClientRequest
from pyfect.logger import log_info, log_warning
from pyfect.option import Some
from pyfect.schema import SchemaError
from pyfect.scope import Scope, add_finalizer

API_URL = "https://kubernetes.default.svc/api"
TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"


class K8sHttpClient(
    Tag[HttpClientService[HttpClientError, Never]], key="effect/cluster/K8sHttpClient"
):
    """The HTTP client for the Kubernetes API."""


@dataclass(frozen=True, slots=True)
class PodCondition:
    type: str
    status: str
    last_transition_time: str | None


class _Absent:
    """A condition that is not in the status (Effect's ``undefined``)."""


_ABSENT = _Absent()


@dataclass(frozen=True, slots=True)
class PodStatus:
    """The part of a pod's status the cluster reads."""

    phase: str
    conditions: tuple[PodCondition, ...]
    pod_ip: str
    host_ip: str


@dataclass(frozen=True, slots=True)
class Pod:
    status: PodStatus

    @property
    def is_ready(self) -> bool:
        for condition in self.status.conditions:
            if condition.type == "Ready":
                return condition.status == "True"
        return False

    @property
    def is_ready_or_initializing(self) -> bool:
        """Ready, or still booting (such a pod has already registered
        itself with runner storage). A condition's null transition time
        differs from a missing condition, as Effect's ``null`` and
        ``undefined`` do."""
        initialized_at: str | _Absent | None = _ABSENT
        ready_at: str | _Absent | None = _ABSENT
        for condition in self.status.conditions:
            match condition.type:
                case "Initialized":
                    if condition.status != "True":
                        return True
                    initialized_at = condition.last_transition_time
                case "Ready":
                    if condition.status == "True":
                        return True
                    ready_at = condition.last_transition_time
                case _:
                    pass
        return initialized_at == ready_at


POD_CONDITION = wire_codec(
    PodCondition,
    [
        key("type", "type", S.String),
        key("status", "status", S.String),
        key("lastTransitionTime", "last_transition_time", S.NullOr(S.String)),
    ],
)
POD_STATUS = wire_codec(
    PodStatus,
    [
        key("phase", "phase", S.String),
        key("conditions", "conditions", S.Array(POD_CONDITION)),
        key("podIP", "pod_ip", S.String),
        key("hostIP", "host_ip", S.String),
    ],
    identifier="@effect/cluster/K8sHttpClient/PodStatus",
)
POD = wire_codec(
    Pod, [key("status", "status", POD_STATUS)], identifier="@effect/cluster/K8sHttpClient/Pod"
)


class _PodList(S.Class):
    items: tuple[Pod, ...] = S.field(S.Array(POD))


def _make_client() -> Generator[
    Effect[Any, Any, Any], Any, HttpClientService[HttpClientError, Never]
]:
    fs = yield from FileSystem()
    token = yield from (
        fs.read_file_string(TOKEN_PATH).map(str.strip).option().cached_with_ttl("60 seconds")
    )
    http = yield from HttpClient()

    def authorize(request: HttpClientRequest) -> Effect[HttpClientRequest]:
        return token.map(
            lambda found: request if found is None else request.bearer_token(found.value)
        )

    return (
        http.map_request(lambda request: request.prepend_url(API_URL))
        .map_request_effect(authorize)
        .filter_status_ok()
        .retry_transient(schedule=schedule.spaced("5 seconds"))
    )


layer: layer_.Layer[K8sHttpClient, Never, HttpClient | FileSystem] = layer_.effect(
    K8sHttpClient, gen(_make_client)
)
"""A ``K8sHttpClient`` on the ``HttpClient``, sending the pod's service account token
(read through the ``FileSystem``) to the cluster's API server."""


def _is_status(status: int) -> Callable[[object], bool]:
    def check(error: object) -> bool:
        return (
            isinstance(error, HttpClientError)
            and isinstance(error.reason, StatusCodeError)
            and error.reason.response.status == status
        )

    return check


def make_get_pods(
    *, namespace: str | None = None, label_selector: str | None = None
) -> Effect[Effect[dict[str, Pod], HttpClientError | SchemaError], Never, K8sHttpClient]:
    """A cached (ten seconds) read of the running pods, keyed by pod IP."""

    def body() -> Generator[Effect[Any, Any, Any], Any, Any]:
        client = yield from K8sHttpClient()
        request = request_.get(
            f"/v1/namespaces/{namespace}/pods" if namespace else "/v1/pods"
        ).set_url_param("fieldSelector", "status.phase=Running")
        if label_selector:
            request = request.set_url_param("labelSelector", label_selector)

        def by_ip(pods: _PodList) -> dict[str, Pod]:
            return {pod.status.pod_ip: pod for pod in pods.items}

        return (
            yield from client.execute(request)
            .flat_map(response_.schema_body_json(_PodList))
            .map(by_ip)
            .tap_cause(lambda cause: log_warning("Failed to fetch pods from Kubernetes API", cause))
            .cached_with_ttl("10 seconds")
        )

    return gen(body)


type CreatePod = Callable[[K8sPod], Effect[PodStatus, Never, Scope]]


def _make_create_pod() -> Generator[Effect[Any, Any, Any], Any, CreatePod]:
    client = yield from K8sHttpClient()

    def create(spec: K8sPod) -> Effect[PodStatus, Never, Scope]:
        # Effect spreads ``spec`` last, so its own metadata wins whole
        full: dict[str, Any] = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"namespace": "default", **spec.get("metadata", {})},
            **spec,
        }
        metadata = full["metadata"]
        namespace = or_default(metadata.get("namespace"), "default")
        name = metadata["name"]
        pod_url = f"/v1/namespaces/{namespace}/pods/{name}"
        read_raw = client.execute(request_.get(pod_url))
        read_pod: Effect[Pod | None] = (
            read_raw.flat_map(response_.schema_body_json(POD))
            .map(Some)
            .retry(
                while_=lambda e: isinstance(e, SchemaError), schedule=schedule.spaced("1 second")
            )
            .catch_if(_is_status(404), lambda _: succeed(None))
            .map(lambda found: None if found is None else found.value)
            .or_die()
        )
        is_pod_found = read_raw.as_(True).catch_if(_is_status(404), lambda _: succeed(False))
        create_pod = (
            client.execute(request_.post(f"/v1/namespaces/{namespace}/pods").body_json_unsafe(full))
            .as_void()
            .catch_if(_is_status(409), lambda _: read_pod.as_void())
            .tap_cause(log_info)
            .or_die()
        )
        delete_pod = (
            client.execute(request_.delete(pod_url))
            .flat_map(lambda response: response.json)
            .as_void()
            .catch_if(_is_status(404), lambda _: void)
            .tap_cause(log_info)
            .or_die()
        )
        wait_deleted = is_pod_found.repeat(
            until=lambda found: not found, schedule=schedule.spaced("3 seconds")
        ).or_die()

        def body() -> Generator[Effect[Any, Any, Any], Any, PodStatus]:
            yield from add_finalizer(
                lambda _: delete_pod.flat_map(lambda _: wait_deleted).as_void()
            )
            pod: Pod | None = None
            while pod is None or not pod.is_ready:
                if pod is None:
                    yield from create_pod
                yield from sleep("3 seconds")
                pod = yield from read_pod
            return pod.status

        return gen(body).with_span("K8sHttpClient.createPod")

    return create


make_create_pod: Effect[CreatePod, Never, K8sHttpClient] = gen(_make_create_pod)
"""A function creating a pod (in ``default`` unless its metadata names a
namespace) that is deleted when the caller's scope closes; it returns the
pod's status once ready."""

__all__ = [
    "API_URL",
    "POD",
    "POD_CONDITION",
    "POD_STATUS",
    "TOKEN_PATH",
    "CreatePod",
    "K8sHttpClient",
    "Pod",
    "PodCondition",
    "PodStatus",
    "layer",
    "make_create_pod",
    "make_get_pods",
]
