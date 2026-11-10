import os

import pyfect as fx
from pyfect import schema as S
from pyfect.cluster import cluster_socket, entity_resource, k8s_types
from pyfect.cluster.entity import CurrentAddress, Entity
from pyfect.rpc import make as make_rpc
from pyfect.sql import pg


class Sandbox(Entity, type="Sandbox"):
    phase = make_rpc("Phase", success=S.String)


def sandbox_pod(entity_id: str) -> k8s_types.Pod:
    # A whole Pod manifest: metadata (name and namespace) and its spec.
    return {
        "metadata": {"name": f"sandbox-{entity_id}", "namespace": "jobs"},
        "spec": {
            "containers": [{"name": "sandbox", "image": "registry.example.com/sandbox:1"}],
            "restartPolicy": "Never",
        },
    }


@fx.gen
def handlers():
    address = yield from CurrentAddress()
    # One pod per entity, created on first use and deleted after 5 idle minutes.
    pod = yield from entity_resource.make_k8s_pod(
        sandbox_pod(str(address.entity_id)), idle_time_to_live="5 minutes"
    )

    def phase(_: object) -> fx.Effect[str]:
        return fx.scoped(pod.get.map(lambda status: status.phase))

    return Sandbox.handlers().handle(Sandbox.phase)(phase)


runner = (
    Sandbox.to_layer_effect(handlers)
    # The Kubernetes API client, trusting the service account's CA.
    .pipe(fx.layer.provide(cluster_socket.layer_k8s_http_client))
    .pipe(
        fx.layer.provide_merge(
            cluster_socket.layer(
                runner_health="k8s",
                runner_health_k8s_namespace="jobs",
                runner_health_k8s_label_selector="app=runner",
            )
        )
    )
    .pipe(fx.layer.provide(pg.layer_config({"url": fx.config.redacted("DATABASE_URL")})))
)

# Kubernetes sets KUBERNETES_SERVICE_HOST in every pod.
if os.environ.get("KUBERNETES_SERVICE_HOST"):
    fx.run_main(runner.launch())
