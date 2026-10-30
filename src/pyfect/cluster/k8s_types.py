"""Kubernetes resource types for the cluster's Kubernetes helpers (Effect's
``K8sTypes``): the transitive closure of ``Pod`` from kubernetes-types
1.30.0, generated from the Kubernetes OpenAPI definitions
(https://github.com/silverlyra/kubernetes-types, Apache-2.0), as
``TypedDict``s of the API's JSON. Field documentation is the Kubernetes API
reference's.

Generated from Effect's ``K8sTypes.ts``.
"""

from typing import Literal, NotRequired, ReadOnly, TypedDict

type Time = str
"""An RFC 3339 timestamp."""

type Quantity = str
"""A fixed-point number with an optional SI suffix (``"500m"``, ``"1Gi"``)."""


class AWSElasticBlockStoreVolumeSource(TypedDict):
    """Represents a Persistent Disk resource in AWS."""

    fsType: NotRequired[str]
    partition: NotRequired[int]
    readOnly: NotRequired[bool]
    volumeID: str


class NodeSelectorRequirement(TypedDict):
    """A node selector requirement is a selector that contains values, a key, and an operator
    that relates the key and values.
    """

    key: str
    operator: str
    values: NotRequired[list[str]]


class NodeSelectorTerm(TypedDict):
    """A null or empty node selector term matches no objects. The requirements of them are
    ANDed. The TopologySelectorTerm type implements a subset of the NodeSelectorTerm.
    """

    matchExpressions: NotRequired[list[NodeSelectorRequirement]]
    matchFields: NotRequired[list[NodeSelectorRequirement]]


class PreferredSchedulingTerm(TypedDict):
    """An empty preferred scheduling term matches all objects with implicit weight 0 (i.e. it's
    a no-op). A null preferred scheduling term matches no objects (i.e. is also a no-op).
    """

    preference: NodeSelectorTerm
    weight: int


class NodeSelector(TypedDict):
    """A node selector represents the union of the results of one or more label queries over a
    set of nodes; that is, it represents the OR of the selectors represented by the node
    selector terms.
    """

    nodeSelectorTerms: list[NodeSelectorTerm]


class NodeAffinity(TypedDict):
    """Node affinity is a group of node affinity scheduling rules."""

    preferredDuringSchedulingIgnoredDuringExecution: NotRequired[list[PreferredSchedulingTerm]]
    requiredDuringSchedulingIgnoredDuringExecution: NotRequired[NodeSelector]


class LabelSelectorRequirement(TypedDict):
    """A label selector requirement is a selector that contains values, a key, and an operator
    that relates the key and values.
    """

    key: str
    operator: str
    values: NotRequired[list[str]]


class LabelSelector(TypedDict):
    """A label selector is a label query over a set of resources. The result of matchLabels and
    matchExpressions are ANDed. An empty label selector matches all objects. A null label
    selector matches no objects.
    """

    matchExpressions: NotRequired[list[LabelSelectorRequirement]]
    matchLabels: NotRequired[dict[str, str]]


class PodAffinityTerm(TypedDict):
    """Defines a set of pods (namely those matching the labelSelector relative to the given
    namespace(s)) that this pod should be co-located (affinity) or not co-located (anti-
    affinity) with, where co-located is defined as running on a node whose value of the
    label with key <topologyKey> matches that of any node on which a pod of the set of pods
    is running
    """

    labelSelector: NotRequired[LabelSelector]
    matchLabelKeys: NotRequired[list[str]]
    mismatchLabelKeys: NotRequired[list[str]]
    namespaceSelector: NotRequired[LabelSelector]
    namespaces: NotRequired[list[str]]
    topologyKey: str


class WeightedPodAffinityTerm(TypedDict):
    """The weights of all of the matched WeightedPodAffinityTerm fields are added per-node to
    find the most preferred node(s)
    """

    podAffinityTerm: PodAffinityTerm
    weight: int


class PodAffinity(TypedDict):
    """Pod affinity is a group of inter pod affinity scheduling rules."""

    preferredDuringSchedulingIgnoredDuringExecution: NotRequired[list[WeightedPodAffinityTerm]]
    requiredDuringSchedulingIgnoredDuringExecution: NotRequired[list[PodAffinityTerm]]


class PodAntiAffinity(TypedDict):
    """Pod anti affinity is a group of inter pod anti affinity scheduling rules."""

    preferredDuringSchedulingIgnoredDuringExecution: NotRequired[list[WeightedPodAffinityTerm]]
    requiredDuringSchedulingIgnoredDuringExecution: NotRequired[list[PodAffinityTerm]]


class Affinity(TypedDict):
    """Affinity is a group of affinity scheduling rules."""

    nodeAffinity: NotRequired[NodeAffinity]
    podAffinity: NotRequired[PodAffinity]
    podAntiAffinity: NotRequired[PodAntiAffinity]


class AppArmorProfile(TypedDict):
    """AppArmorProfile defines a pod or container's AppArmor settings."""

    localhostProfile: NotRequired[str]
    type: str


class AzureDiskVolumeSource(TypedDict):
    """AzureDisk represents an Azure Data Disk mount on the host and bind mount to the pod."""

    cachingMode: NotRequired[str]
    diskName: str
    diskURI: str
    fsType: NotRequired[str]
    kind: NotRequired[str]
    readOnly: NotRequired[bool]


class AzureFileVolumeSource(TypedDict):
    """AzureFile represents an Azure File Service mount on the host and bind mount to the pod."""

    readOnly: NotRequired[bool]
    secretName: str
    shareName: str


class LocalObjectReference(TypedDict):
    """LocalObjectReference contains enough information to let you locate the referenced object
    inside the same namespace.
    """

    name: NotRequired[str]


class CSIVolumeSource(TypedDict):
    """Represents a source location of a volume to mount, managed by an external CSI driver"""

    driver: str
    fsType: NotRequired[str]
    nodePublishSecretRef: NotRequired[LocalObjectReference]
    readOnly: NotRequired[bool]
    volumeAttributes: NotRequired[dict[str, str]]


class Capabilities(TypedDict):
    """Adds and removes POSIX capabilities from running containers."""

    add: NotRequired[list[str]]
    drop: NotRequired[list[str]]


class CephFSVolumeSource(TypedDict):
    """Represents a Ceph Filesystem mount that lasts the lifetime of a pod Cephfs volumes do
    not support ownership management or SELinux relabeling.
    """

    monitors: list[str]
    path: NotRequired[str]
    readOnly: NotRequired[bool]
    secretFile: NotRequired[str]
    secretRef: NotRequired[LocalObjectReference]
    user: NotRequired[str]


class CinderVolumeSource(TypedDict):
    """Represents a cinder volume resource in Openstack. A Cinder volume must exist before
    mounting to a container. The volume must also be in the same region as the kubelet.
    Cinder volumes support ownership management and SELinux relabeling.
    """

    fsType: NotRequired[str]
    readOnly: NotRequired[bool]
    secretRef: NotRequired[LocalObjectReference]
    volumeID: str


class ClaimSource(TypedDict):
    """ClaimSource describes a reference to a ResourceClaim."""

    resourceClaimName: NotRequired[str]
    resourceClaimTemplateName: NotRequired[str]


class ClusterTrustBundleProjection(TypedDict):
    """ClusterTrustBundleProjection describes how to select a set of ClusterTrustBundle objects
    and project their contents into the pod filesystem.
    """

    labelSelector: NotRequired[LabelSelector]
    name: NotRequired[str]
    optional: NotRequired[bool]
    path: str
    signerName: NotRequired[str]


class ConfigMapEnvSource(TypedDict):
    """ConfigMapEnvSource selects a ConfigMap to populate the environment variables with."""

    name: NotRequired[str]
    optional: NotRequired[bool]


class ConfigMapKeySelector(TypedDict):
    """Selects a key from a ConfigMap."""

    key: str
    name: NotRequired[str]
    optional: NotRequired[bool]


class KeyToPath(TypedDict):
    """Maps a string key to a path within a volume."""

    key: str
    mode: NotRequired[int]
    path: str


class ConfigMapProjection(TypedDict):
    """Adapts a ConfigMap into a projected volume."""

    items: NotRequired[list[KeyToPath]]
    name: NotRequired[str]
    optional: NotRequired[bool]


class ConfigMapVolumeSource(TypedDict):
    """Adapts a ConfigMap into a volume."""

    defaultMode: NotRequired[int]
    items: NotRequired[list[KeyToPath]]
    name: NotRequired[str]
    optional: NotRequired[bool]


class ObjectFieldSelector(TypedDict):
    """ObjectFieldSelector selects an APIVersioned field of an object."""

    apiVersion: NotRequired[str]
    fieldPath: str


class ResourceFieldSelector(TypedDict):
    """ResourceFieldSelector represents container resources (cpu, memory) and their output
    format
    """

    containerName: NotRequired[str]
    divisor: NotRequired[Quantity]
    resource: str


class SecretKeySelector(TypedDict):
    """SecretKeySelector selects a key of a Secret."""

    key: str
    name: NotRequired[str]
    optional: NotRequired[bool]


class EnvVarSource(TypedDict):
    """EnvVarSource represents a source for the value of an EnvVar."""

    configMapKeyRef: NotRequired[ConfigMapKeySelector]
    fieldRef: NotRequired[ObjectFieldSelector]
    resourceFieldRef: NotRequired[ResourceFieldSelector]
    secretKeyRef: NotRequired[SecretKeySelector]


class EnvVar(TypedDict):
    """EnvVar represents an environment variable present in a Container."""

    name: str
    value: NotRequired[str]
    valueFrom: NotRequired[EnvVarSource]


class SecretEnvSource(TypedDict):
    """SecretEnvSource selects a Secret to populate the environment variables with."""

    name: NotRequired[str]
    optional: NotRequired[bool]


class EnvFromSource(TypedDict):
    """EnvFromSource represents the source of a set of ConfigMaps"""

    configMapRef: NotRequired[ConfigMapEnvSource]
    prefix: NotRequired[str]
    secretRef: NotRequired[SecretEnvSource]


class ExecAction(TypedDict):
    """ExecAction describes a "run in container" action."""

    command: NotRequired[list[str]]


class HTTPHeader(TypedDict):
    """HTTPHeader describes a custom header to be used in HTTP probes"""

    name: str
    value: str


class HTTPGetAction(TypedDict):
    """HTTPGetAction describes an action based on HTTP Get requests."""

    host: NotRequired[str]
    httpHeaders: NotRequired[list[HTTPHeader]]
    path: NotRequired[str]
    port: int | str
    scheme: NotRequired[str]


class SleepAction(TypedDict):
    """SleepAction describes a "sleep" action."""

    seconds: int


class TCPSocketAction(TypedDict):
    """TCPSocketAction describes an action based on opening a socket"""

    host: NotRequired[str]
    port: int | str


class LifecycleHandler(TypedDict):
    """LifecycleHandler defines a specific action that should be taken in a lifecycle hook. One
    and only one of the fields, except TCPSocket must be specified.
    """

    exec: NotRequired[ExecAction]
    httpGet: NotRequired[HTTPGetAction]
    sleep: NotRequired[SleepAction]
    tcpSocket: NotRequired[TCPSocketAction]


class Lifecycle(TypedDict):
    """Lifecycle describes actions that the management system should take in response to
    container lifecycle events. For the PostStart and PreStop lifecycle handlers, management
    of the container blocks until the action is complete, unless the container process
    fails, in which case the handler is aborted.
    """

    postStart: NotRequired[LifecycleHandler]
    preStop: NotRequired[LifecycleHandler]


class GRPCAction(TypedDict):
    """GRPCAction specifies an action involving a gRPC service."""

    port: int
    service: NotRequired[str]


class Probe(TypedDict):
    """Probe describes a health check to be performed against a container to determine whether
    it is alive or ready to receive traffic.
    """

    exec: NotRequired[ExecAction]
    failureThreshold: NotRequired[int]
    grpc: NotRequired[GRPCAction]
    httpGet: NotRequired[HTTPGetAction]
    initialDelaySeconds: NotRequired[int]
    periodSeconds: NotRequired[int]
    successThreshold: NotRequired[int]
    tcpSocket: NotRequired[TCPSocketAction]
    terminationGracePeriodSeconds: NotRequired[int]
    timeoutSeconds: NotRequired[int]


class ContainerPort(TypedDict):
    """ContainerPort represents a network port in a single container."""

    containerPort: int
    hostIP: NotRequired[str]
    hostPort: NotRequired[int]
    name: NotRequired[str]
    protocol: NotRequired[str]


class ContainerResizePolicy(TypedDict):
    """ContainerResizePolicy represents resource resize policy for the container."""

    resourceName: str
    restartPolicy: str


class ResourceClaim(TypedDict):
    """ResourceClaim references one entry in PodSpec.ResourceClaims."""

    name: str


class ResourceRequirements(TypedDict):
    """ResourceRequirements describes the compute resource requirements."""

    claims: NotRequired[list[ResourceClaim]]
    limits: NotRequired[dict[str, Quantity]]
    requests: NotRequired[dict[str, Quantity]]


class SELinuxOptions(TypedDict):
    """SELinuxOptions are the labels to be applied to the container"""

    level: NotRequired[str]
    role: NotRequired[str]
    type: NotRequired[str]
    user: NotRequired[str]


class SeccompProfile(TypedDict):
    """SeccompProfile defines a pod/container's seccomp profile settings. Only one profile
    source may be set.
    """

    localhostProfile: NotRequired[str]
    type: str


class WindowsSecurityContextOptions(TypedDict):
    """WindowsSecurityContextOptions contain Windows-specific options and credentials."""

    gmsaCredentialSpec: NotRequired[str]
    gmsaCredentialSpecName: NotRequired[str]
    hostProcess: NotRequired[bool]
    runAsUserName: NotRequired[str]


class SecurityContext(TypedDict):
    """SecurityContext holds security configuration that will be applied to a container. Some
    fields are present in both SecurityContext and PodSecurityContext.  When both are set,
    the values in SecurityContext take precedence.
    """

    allowPrivilegeEscalation: NotRequired[bool]
    appArmorProfile: NotRequired[AppArmorProfile]
    capabilities: NotRequired[Capabilities]
    privileged: NotRequired[bool]
    procMount: NotRequired[str]
    readOnlyRootFilesystem: NotRequired[bool]
    runAsGroup: NotRequired[int]
    runAsNonRoot: NotRequired[bool]
    runAsUser: NotRequired[int]
    seLinuxOptions: NotRequired[SELinuxOptions]
    seccompProfile: NotRequired[SeccompProfile]
    windowsOptions: NotRequired[WindowsSecurityContextOptions]


class VolumeDevice(TypedDict):
    """volumeDevice describes a mapping of a raw block device within a container."""

    devicePath: str
    name: str


class VolumeMount(TypedDict):
    """VolumeMount describes a mounting of a Volume within a container."""

    mountPath: str
    mountPropagation: NotRequired[str]
    name: str
    readOnly: NotRequired[bool]
    recursiveReadOnly: NotRequired[str]
    subPath: NotRequired[str]
    subPathExpr: NotRequired[str]


class Container(TypedDict):
    """A single application container that you want to run within a pod."""

    args: NotRequired[list[str]]
    command: NotRequired[list[str]]
    env: NotRequired[list[EnvVar]]
    envFrom: NotRequired[list[EnvFromSource]]
    image: NotRequired[str]
    imagePullPolicy: NotRequired[str]
    lifecycle: NotRequired[Lifecycle]
    livenessProbe: NotRequired[Probe]
    name: str
    ports: NotRequired[list[ContainerPort]]
    readinessProbe: NotRequired[Probe]
    resizePolicy: NotRequired[list[ContainerResizePolicy]]
    resources: NotRequired[ResourceRequirements]
    restartPolicy: NotRequired[str]
    securityContext: NotRequired[SecurityContext]
    startupProbe: NotRequired[Probe]
    stdin: NotRequired[bool]
    stdinOnce: NotRequired[bool]
    terminationMessagePath: NotRequired[str]
    terminationMessagePolicy: NotRequired[str]
    tty: NotRequired[bool]
    volumeDevices: NotRequired[list[VolumeDevice]]
    volumeMounts: NotRequired[list[VolumeMount]]
    workingDir: NotRequired[str]


class ContainerStateRunning(TypedDict):
    """ContainerStateRunning is a running state of a container."""

    startedAt: NotRequired[Time]


class ContainerStateTerminated(TypedDict):
    """ContainerStateTerminated is a terminated state of a container."""

    containerID: NotRequired[str]
    exitCode: int
    finishedAt: NotRequired[Time]
    message: NotRequired[str]
    reason: NotRequired[str]
    signal: NotRequired[int]
    startedAt: NotRequired[Time]


class ContainerStateWaiting(TypedDict):
    """ContainerStateWaiting is a waiting state of a container."""

    message: NotRequired[str]
    reason: NotRequired[str]


class ContainerState(TypedDict):
    """ContainerState holds a possible state of container. Only one of its members may be
    specified. If none of them is specified, the default one is ContainerStateWaiting.
    """

    running: NotRequired[ContainerStateRunning]
    terminated: NotRequired[ContainerStateTerminated]
    waiting: NotRequired[ContainerStateWaiting]


class VolumeMountStatus(TypedDict):
    """VolumeMountStatus shows status of volume mounts."""

    mountPath: str
    name: str
    readOnly: NotRequired[bool]
    recursiveReadOnly: NotRequired[str]


class ContainerStatus(TypedDict):
    """ContainerStatus contains details for the current status of this container."""

    allocatedResources: NotRequired[dict[str, Quantity]]
    containerID: NotRequired[str]
    image: str
    imageID: str
    lastState: NotRequired[ContainerState]
    name: str
    ready: bool
    resources: NotRequired[ResourceRequirements]
    restartCount: int
    started: NotRequired[bool]
    state: NotRequired[ContainerState]
    volumeMounts: NotRequired[list[VolumeMountStatus]]


class DownwardAPIVolumeFile(TypedDict):
    """DownwardAPIVolumeFile represents information to create the file containing the pod field"""

    fieldRef: NotRequired[ObjectFieldSelector]
    mode: NotRequired[int]
    path: str
    resourceFieldRef: NotRequired[ResourceFieldSelector]


class DownwardAPIProjection(TypedDict):
    """Represents downward API info for projecting into a projected volume. Note that this is
    identical to a downwardAPI volume source without the default mode.
    """

    items: NotRequired[list[DownwardAPIVolumeFile]]


class DownwardAPIVolumeSource(TypedDict):
    """DownwardAPIVolumeSource represents a volume containing downward API info. Downward API
    volumes support ownership management and SELinux relabeling.
    """

    defaultMode: NotRequired[int]
    items: NotRequired[list[DownwardAPIVolumeFile]]


class EmptyDirVolumeSource(TypedDict):
    """Represents an empty directory for a pod. Empty directory volumes support ownership
    management and SELinux relabeling.
    """

    medium: NotRequired[str]
    sizeLimit: NotRequired[Quantity]


class EphemeralContainer(TypedDict):
    """An EphemeralContainer is a temporary container that you may add to an existing Pod for
    user-initiated activities such as debugging. Ephemeral containers have no resource or
    scheduling guarantees, and they will not be restarted when they exit or when a Pod is
    removed or restarted. The kubelet may evict a Pod if an ephemeral container causes the
    Pod to exceed its resource allocation.
    """

    args: NotRequired[list[str]]
    command: NotRequired[list[str]]
    env: NotRequired[list[EnvVar]]
    envFrom: NotRequired[list[EnvFromSource]]
    image: NotRequired[str]
    imagePullPolicy: NotRequired[str]
    lifecycle: NotRequired[Lifecycle]
    livenessProbe: NotRequired[Probe]
    name: str
    ports: NotRequired[list[ContainerPort]]
    readinessProbe: NotRequired[Probe]
    resizePolicy: NotRequired[list[ContainerResizePolicy]]
    resources: NotRequired[ResourceRequirements]
    restartPolicy: NotRequired[str]
    securityContext: NotRequired[SecurityContext]
    startupProbe: NotRequired[Probe]
    stdin: NotRequired[bool]
    stdinOnce: NotRequired[bool]
    targetContainerName: NotRequired[str]
    terminationMessagePath: NotRequired[str]
    terminationMessagePolicy: NotRequired[str]
    tty: NotRequired[bool]
    volumeDevices: NotRequired[list[VolumeDevice]]
    volumeMounts: NotRequired[list[VolumeMount]]
    workingDir: NotRequired[str]


class FieldsV1(TypedDict):
    """FieldsV1 stores a set of fields in a data structure like a Trie, in JSON format."""

    pass


class ManagedFieldsEntry(TypedDict):
    """ManagedFieldsEntry is a workflow-id, a FieldSet and the group version of the resource
    that the fieldset applies to.
    """

    apiVersion: NotRequired[str]
    fieldsType: NotRequired[str]
    fieldsV1: NotRequired[FieldsV1]
    manager: NotRequired[str]
    operation: NotRequired[str]
    subresource: NotRequired[str]
    time: NotRequired[Time]


class OwnerReference(TypedDict):
    """OwnerReference contains enough information to let you identify an owning object. An
    owning object must be in the same namespace as the dependent, or be cluster-scoped, so
    there is no namespace field.
    """

    apiVersion: str
    blockOwnerDeletion: NotRequired[bool]
    controller: NotRequired[bool]
    kind: str
    name: str
    uid: str


class ObjectMeta(TypedDict):
    """ObjectMeta is metadata that all persisted resources must have, which includes all
    objects users must create.
    """

    annotations: NotRequired[dict[str, str]]
    creationTimestamp: NotRequired[ReadOnly[Time]]
    deletionGracePeriodSeconds: NotRequired[ReadOnly[int]]
    deletionTimestamp: NotRequired[ReadOnly[Time]]
    finalizers: NotRequired[list[str]]
    generateName: NotRequired[str]
    generation: NotRequired[ReadOnly[int]]
    labels: NotRequired[dict[str, str]]
    managedFields: NotRequired[list[ManagedFieldsEntry]]
    name: NotRequired[str]
    namespace: NotRequired[str]
    ownerReferences: NotRequired[list[OwnerReference]]
    resourceVersion: NotRequired[ReadOnly[str]]
    selfLink: NotRequired[str]
    uid: NotRequired[ReadOnly[str]]


class TypedLocalObjectReference(TypedDict):
    """TypedLocalObjectReference contains enough information to let you locate the typed
    referenced object inside the same namespace.
    """

    apiGroup: NotRequired[str]
    kind: str
    name: str


class TypedObjectReference(TypedDict):
    """TypedObjectReference contains enough information to locate a typed referenced object."""

    apiGroup: NotRequired[str]
    kind: str
    name: str
    namespace: NotRequired[str]


class VolumeResourceRequirements(TypedDict):
    """VolumeResourceRequirements describes the storage resource requirements for a volume."""

    limits: NotRequired[dict[str, Quantity]]
    requests: NotRequired[dict[str, Quantity]]


class PersistentVolumeClaimSpec(TypedDict):
    """PersistentVolumeClaimSpec describes the common attributes of storage devices and allows
    a Source for provider-specific attributes
    """

    accessModes: NotRequired[list[str]]
    dataSource: NotRequired[TypedLocalObjectReference]
    dataSourceRef: NotRequired[TypedObjectReference]
    resources: NotRequired[VolumeResourceRequirements]
    selector: NotRequired[LabelSelector]
    storageClassName: NotRequired[str]
    volumeAttributesClassName: NotRequired[str]
    volumeMode: NotRequired[str]
    volumeName: NotRequired[str]


class PersistentVolumeClaimTemplate(TypedDict):
    """PersistentVolumeClaimTemplate is used to produce PersistentVolumeClaim objects as part
    of an EphemeralVolumeSource.
    """

    metadata: NotRequired[ObjectMeta]
    spec: PersistentVolumeClaimSpec


class EphemeralVolumeSource(TypedDict):
    """Represents an ephemeral volume that is handled by a normal storage driver."""

    volumeClaimTemplate: NotRequired[PersistentVolumeClaimTemplate]


class FCVolumeSource(TypedDict):
    """Represents a Fibre Channel volume. Fibre Channel volumes can only be mounted as
    read/write once. Fibre Channel volumes support ownership management and SELinux
    relabeling.
    """

    fsType: NotRequired[str]
    lun: NotRequired[int]
    readOnly: NotRequired[bool]
    targetWWNs: NotRequired[list[str]]
    wwids: NotRequired[list[str]]


class FlexVolumeSource(TypedDict):
    """FlexVolume represents a generic volume resource that is provisioned/attached using an
    exec based plugin.
    """

    driver: str
    fsType: NotRequired[str]
    options: NotRequired[dict[str, str]]
    readOnly: NotRequired[bool]
    secretRef: NotRequired[LocalObjectReference]


class FlockerVolumeSource(TypedDict):
    """Represents a Flocker volume mounted by the Flocker agent. One and only one of
    datasetName and datasetUUID should be set. Flocker volumes do not support ownership
    management or SELinux relabeling.
    """

    datasetName: NotRequired[str]
    datasetUUID: NotRequired[str]


class GCEPersistentDiskVolumeSource(TypedDict):
    """Represents a Persistent Disk resource in Google Compute Engine."""

    fsType: NotRequired[str]
    partition: NotRequired[int]
    pdName: str
    readOnly: NotRequired[bool]


class GitRepoVolumeSource(TypedDict):
    """Represents a volume that is populated with the contents of a git repository. Git repo
    volumes do not support ownership management. Git repo volumes support SELinux
    relabeling.
    """

    directory: NotRequired[str]
    repository: str
    revision: NotRequired[str]


class GlusterfsVolumeSource(TypedDict):
    """Represents a Glusterfs mount that lasts the lifetime of a pod. Glusterfs volumes do not
    support ownership management or SELinux relabeling.
    """

    endpoints: str
    path: str
    readOnly: NotRequired[bool]


class HostAlias(TypedDict):
    """HostAlias holds the mapping between IP and hostnames that will be injected as an entry
    in the pod's hosts file.
    """

    hostnames: NotRequired[list[str]]
    ip: NotRequired[str]


class HostIP(TypedDict):
    """HostIP represents a single IP address allocated to the host."""

    ip: NotRequired[str]


class HostPathVolumeSource(TypedDict):
    """Represents a host path mapped into a pod. Host path volumes do not support ownership
    management or SELinux relabeling.
    """

    path: str
    type: NotRequired[str]


class ISCSIVolumeSource(TypedDict):
    """Represents an ISCSI disk. ISCSI volumes can only be mounted as read/write once. ISCSI
    volumes support ownership management and SELinux relabeling.
    """

    chapAuthDiscovery: NotRequired[bool]
    chapAuthSession: NotRequired[bool]
    fsType: NotRequired[str]
    initiatorName: NotRequired[str]
    iqn: str
    iscsiInterface: NotRequired[str]
    lun: int
    portals: NotRequired[list[str]]
    readOnly: NotRequired[bool]
    secretRef: NotRequired[LocalObjectReference]
    targetPortal: str


class NFSVolumeSource(TypedDict):
    """Represents an NFS mount that lasts the lifetime of a pod. NFS volumes do not support
    ownership management or SELinux relabeling.
    """

    path: str
    readOnly: NotRequired[bool]
    server: str


class PersistentVolumeClaimVolumeSource(TypedDict):
    """PersistentVolumeClaimVolumeSource references the user's PVC in the same namespace. This
    volume finds the bound PV and mounts that volume for the pod. A
    PersistentVolumeClaimVolumeSource is, essentially, a wrapper around another type of
    volume that is owned by someone else (the system).
    """

    claimName: str
    readOnly: NotRequired[bool]


class PhotonPersistentDiskVolumeSource(TypedDict):
    """Represents a Photon Controller persistent disk resource."""

    fsType: NotRequired[str]
    pdID: str


class PodDNSConfigOption(TypedDict):
    """PodDNSConfigOption defines DNS resolver options of a pod."""

    name: NotRequired[str]
    value: NotRequired[str]


class PodDNSConfig(TypedDict):
    """PodDNSConfig defines the DNS parameters of a pod in addition to those generated from
    DNSPolicy.
    """

    nameservers: NotRequired[list[str]]
    options: NotRequired[list[PodDNSConfigOption]]
    searches: NotRequired[list[str]]


class PodOS(TypedDict):
    """PodOS defines the OS parameters of a pod."""

    name: str


class PodReadinessGate(TypedDict):
    """PodReadinessGate contains the reference to a pod condition"""

    conditionType: str


class PodResourceClaim(TypedDict):
    """PodResourceClaim references exactly one ResourceClaim through a ClaimSource. It adds a
    name to it that uniquely identifies the ResourceClaim inside the Pod. Containers that
    need access to the ResourceClaim reference it with this name.
    """

    name: str
    source: NotRequired[ClaimSource]


class PodSchedulingGate(TypedDict):
    """PodSchedulingGate is associated to a Pod to guard its scheduling."""

    name: str


class Sysctl(TypedDict):
    """Sysctl defines a kernel parameter to be set"""

    name: str
    value: str


class PodSecurityContext(TypedDict):
    """PodSecurityContext holds pod-level security attributes and common container settings.
    Some fields are also present in container.securityContext.  Field values of
    container.securityContext take precedence over field values of PodSecurityContext.
    """

    appArmorProfile: NotRequired[AppArmorProfile]
    fsGroup: NotRequired[int]
    fsGroupChangePolicy: NotRequired[str]
    runAsGroup: NotRequired[int]
    runAsNonRoot: NotRequired[bool]
    runAsUser: NotRequired[int]
    seLinuxOptions: NotRequired[SELinuxOptions]
    seccompProfile: NotRequired[SeccompProfile]
    supplementalGroups: NotRequired[list[int]]
    sysctls: NotRequired[list[Sysctl]]
    windowsOptions: NotRequired[WindowsSecurityContextOptions]


class Toleration(TypedDict):
    """The pod this Toleration is attached to tolerates any taint that matches the triple
    <key,value,effect> using the matching operator <operator>.
    """

    effect: NotRequired[str]
    key: NotRequired[str]
    operator: NotRequired[str]
    tolerationSeconds: NotRequired[int]
    value: NotRequired[str]


class TopologySpreadConstraint(TypedDict):
    """TopologySpreadConstraint specifies how to spread matching pods among the given topology."""

    labelSelector: NotRequired[LabelSelector]
    matchLabelKeys: NotRequired[list[str]]
    maxSkew: int
    minDomains: NotRequired[int]
    nodeAffinityPolicy: NotRequired[str]
    nodeTaintsPolicy: NotRequired[str]
    topologyKey: str
    whenUnsatisfiable: str


class PortworxVolumeSource(TypedDict):
    """PortworxVolumeSource represents a Portworx volume resource."""

    fsType: NotRequired[str]
    readOnly: NotRequired[bool]
    volumeID: str


class SecretProjection(TypedDict):
    """Adapts a secret into a projected volume."""

    items: NotRequired[list[KeyToPath]]
    name: NotRequired[str]
    optional: NotRequired[bool]


class ServiceAccountTokenProjection(TypedDict):
    """ServiceAccountTokenProjection represents a projected service account token volume. This
    projection can be used to insert a service account token into the pods runtime
    filesystem for use against APIs (Kubernetes API Server or otherwise).
    """

    audience: NotRequired[str]
    expirationSeconds: NotRequired[int]
    path: str


class VolumeProjection(TypedDict):
    """Projection that may be projected along with other supported volume types"""

    clusterTrustBundle: NotRequired[ClusterTrustBundleProjection]
    configMap: NotRequired[ConfigMapProjection]
    downwardAPI: NotRequired[DownwardAPIProjection]
    secret: NotRequired[SecretProjection]
    serviceAccountToken: NotRequired[ServiceAccountTokenProjection]


class ProjectedVolumeSource(TypedDict):
    """Represents a projected volume source"""

    defaultMode: NotRequired[int]
    sources: NotRequired[list[VolumeProjection]]


class QuobyteVolumeSource(TypedDict):
    """Represents a Quobyte mount that lasts the lifetime of a pod. Quobyte volumes do not
    support ownership management or SELinux relabeling.
    """

    group: NotRequired[str]
    readOnly: NotRequired[bool]
    registry: str
    tenant: NotRequired[str]
    user: NotRequired[str]
    volume: str


class RBDVolumeSource(TypedDict):
    """Represents a Rados Block Device mount that lasts the lifetime of a pod. RBD volumes
    support ownership management and SELinux relabeling.
    """

    fsType: NotRequired[str]
    image: str
    keyring: NotRequired[str]
    monitors: list[str]
    pool: NotRequired[str]
    readOnly: NotRequired[bool]
    secretRef: NotRequired[LocalObjectReference]
    user: NotRequired[str]


class ScaleIOVolumeSource(TypedDict):
    """ScaleIOVolumeSource represents a persistent ScaleIO volume"""

    fsType: NotRequired[str]
    gateway: str
    protectionDomain: NotRequired[str]
    readOnly: NotRequired[bool]
    secretRef: LocalObjectReference
    sslEnabled: NotRequired[bool]
    storageMode: NotRequired[str]
    storagePool: NotRequired[str]
    system: str
    volumeName: NotRequired[str]


class SecretVolumeSource(TypedDict):
    """Adapts a Secret into a volume."""

    defaultMode: NotRequired[int]
    items: NotRequired[list[KeyToPath]]
    optional: NotRequired[bool]
    secretName: NotRequired[str]


class StorageOSVolumeSource(TypedDict):
    """Represents a StorageOS persistent volume resource."""

    fsType: NotRequired[str]
    readOnly: NotRequired[bool]
    secretRef: NotRequired[LocalObjectReference]
    volumeName: NotRequired[str]
    volumeNamespace: NotRequired[str]


class VsphereVirtualDiskVolumeSource(TypedDict):
    """Represents a vSphere volume resource."""

    fsType: NotRequired[str]
    storagePolicyID: NotRequired[str]
    storagePolicyName: NotRequired[str]
    volumePath: str


class Volume(TypedDict):
    """Volume represents a named volume in a pod that may be accessed by any container in the
    pod.
    """

    awsElasticBlockStore: NotRequired[AWSElasticBlockStoreVolumeSource]
    azureDisk: NotRequired[AzureDiskVolumeSource]
    azureFile: NotRequired[AzureFileVolumeSource]
    cephfs: NotRequired[CephFSVolumeSource]
    cinder: NotRequired[CinderVolumeSource]
    configMap: NotRequired[ConfigMapVolumeSource]
    csi: NotRequired[CSIVolumeSource]
    downwardAPI: NotRequired[DownwardAPIVolumeSource]
    emptyDir: NotRequired[EmptyDirVolumeSource]
    ephemeral: NotRequired[EphemeralVolumeSource]
    fc: NotRequired[FCVolumeSource]
    flexVolume: NotRequired[FlexVolumeSource]
    flocker: NotRequired[FlockerVolumeSource]
    gcePersistentDisk: NotRequired[GCEPersistentDiskVolumeSource]
    gitRepo: NotRequired[GitRepoVolumeSource]
    glusterfs: NotRequired[GlusterfsVolumeSource]
    hostPath: NotRequired[HostPathVolumeSource]
    iscsi: NotRequired[ISCSIVolumeSource]
    name: str
    nfs: NotRequired[NFSVolumeSource]
    persistentVolumeClaim: NotRequired[PersistentVolumeClaimVolumeSource]
    photonPersistentDisk: NotRequired[PhotonPersistentDiskVolumeSource]
    portworxVolume: NotRequired[PortworxVolumeSource]
    projected: NotRequired[ProjectedVolumeSource]
    quobyte: NotRequired[QuobyteVolumeSource]
    rbd: NotRequired[RBDVolumeSource]
    scaleIO: NotRequired[ScaleIOVolumeSource]
    secret: NotRequired[SecretVolumeSource]
    storageos: NotRequired[StorageOSVolumeSource]
    vsphereVolume: NotRequired[VsphereVirtualDiskVolumeSource]


class PodSpec(TypedDict):
    """PodSpec is a description of a pod."""

    activeDeadlineSeconds: NotRequired[int]
    affinity: NotRequired[Affinity]
    automountServiceAccountToken: NotRequired[bool]
    containers: list[Container]
    dnsConfig: NotRequired[PodDNSConfig]
    dnsPolicy: NotRequired[str]
    enableServiceLinks: NotRequired[bool]
    ephemeralContainers: NotRequired[list[EphemeralContainer]]
    hostAliases: NotRequired[list[HostAlias]]
    hostIPC: NotRequired[bool]
    hostNetwork: NotRequired[bool]
    hostPID: NotRequired[bool]
    hostUsers: NotRequired[bool]
    hostname: NotRequired[str]
    imagePullSecrets: NotRequired[list[LocalObjectReference]]
    initContainers: NotRequired[list[Container]]
    nodeName: NotRequired[str]
    nodeSelector: NotRequired[dict[str, str]]
    os: NotRequired[PodOS]
    overhead: NotRequired[dict[str, Quantity]]
    preemptionPolicy: NotRequired[str]
    priority: NotRequired[int]
    priorityClassName: NotRequired[str]
    readinessGates: NotRequired[list[PodReadinessGate]]
    resourceClaims: NotRequired[list[PodResourceClaim]]
    restartPolicy: NotRequired[str]
    runtimeClassName: NotRequired[str]
    schedulerName: NotRequired[str]
    schedulingGates: NotRequired[list[PodSchedulingGate]]
    securityContext: NotRequired[PodSecurityContext]
    serviceAccount: NotRequired[str]
    serviceAccountName: NotRequired[str]
    setHostnameAsFQDN: NotRequired[bool]
    shareProcessNamespace: NotRequired[bool]
    subdomain: NotRequired[str]
    terminationGracePeriodSeconds: NotRequired[int]
    tolerations: NotRequired[list[Toleration]]
    topologySpreadConstraints: NotRequired[list[TopologySpreadConstraint]]
    volumes: NotRequired[list[Volume]]


class PodCondition(TypedDict):
    """PodCondition contains details for the current condition of this pod."""

    lastProbeTime: NotRequired[Time]
    lastTransitionTime: NotRequired[Time]
    message: NotRequired[str]
    reason: NotRequired[str]
    status: str
    type: str


class PodIP(TypedDict):
    """PodIP represents a single IP address allocated to the pod."""

    ip: NotRequired[str]


class PodResourceClaimStatus(TypedDict):
    """PodResourceClaimStatus is stored in the PodStatus for each PodResourceClaim which
    references a ResourceClaimTemplate. It stores the generated name for the corresponding
    ResourceClaim.
    """

    name: str
    resourceClaimName: NotRequired[str]


class PodStatus(TypedDict):
    """PodStatus represents information about the status of a pod. Status may trail the actual
    state of a system, especially if the node that hosts the pod cannot contact the control
    plane.
    """

    conditions: NotRequired[list[PodCondition]]
    containerStatuses: NotRequired[list[ContainerStatus]]
    ephemeralContainerStatuses: NotRequired[list[ContainerStatus]]
    hostIP: NotRequired[str]
    hostIPs: NotRequired[list[HostIP]]
    initContainerStatuses: NotRequired[list[ContainerStatus]]
    message: NotRequired[str]
    nominatedNodeName: NotRequired[str]
    phase: NotRequired[str]
    podIP: NotRequired[str]
    podIPs: NotRequired[list[PodIP]]
    qosClass: NotRequired[str]
    reason: NotRequired[str]
    resize: NotRequired[str]
    resourceClaimStatuses: NotRequired[list[PodResourceClaimStatus]]
    startTime: NotRequired[Time]


class Pod(TypedDict):
    """Pod is a collection of containers that can run on a host. This resource is created by
    clients and scheduled onto hosts.
    """

    apiVersion: NotRequired[Literal["v1"]]
    kind: NotRequired[Literal["Pod"]]
    metadata: NotRequired[ObjectMeta]
    spec: NotRequired[PodSpec]
    status: NotRequired[ReadOnly[PodStatus]]


__all__ = [
    "AWSElasticBlockStoreVolumeSource",
    "Affinity",
    "AppArmorProfile",
    "AzureDiskVolumeSource",
    "AzureFileVolumeSource",
    "CSIVolumeSource",
    "Capabilities",
    "CephFSVolumeSource",
    "CinderVolumeSource",
    "ClaimSource",
    "ClusterTrustBundleProjection",
    "ConfigMapEnvSource",
    "ConfigMapKeySelector",
    "ConfigMapProjection",
    "ConfigMapVolumeSource",
    "Container",
    "ContainerPort",
    "ContainerResizePolicy",
    "ContainerState",
    "ContainerStateRunning",
    "ContainerStateTerminated",
    "ContainerStateWaiting",
    "ContainerStatus",
    "DownwardAPIProjection",
    "DownwardAPIVolumeFile",
    "DownwardAPIVolumeSource",
    "EmptyDirVolumeSource",
    "EnvFromSource",
    "EnvVar",
    "EnvVarSource",
    "EphemeralContainer",
    "EphemeralVolumeSource",
    "ExecAction",
    "FCVolumeSource",
    "FieldsV1",
    "FlexVolumeSource",
    "FlockerVolumeSource",
    "GCEPersistentDiskVolumeSource",
    "GRPCAction",
    "GitRepoVolumeSource",
    "GlusterfsVolumeSource",
    "HTTPGetAction",
    "HTTPHeader",
    "HostAlias",
    "HostIP",
    "HostPathVolumeSource",
    "ISCSIVolumeSource",
    "KeyToPath",
    "LabelSelector",
    "LabelSelectorRequirement",
    "Lifecycle",
    "LifecycleHandler",
    "LocalObjectReference",
    "ManagedFieldsEntry",
    "NFSVolumeSource",
    "NodeAffinity",
    "NodeSelector",
    "NodeSelectorRequirement",
    "NodeSelectorTerm",
    "ObjectFieldSelector",
    "ObjectMeta",
    "OwnerReference",
    "PersistentVolumeClaimSpec",
    "PersistentVolumeClaimTemplate",
    "PersistentVolumeClaimVolumeSource",
    "PhotonPersistentDiskVolumeSource",
    "Pod",
    "PodAffinity",
    "PodAffinityTerm",
    "PodAntiAffinity",
    "PodCondition",
    "PodDNSConfig",
    "PodDNSConfigOption",
    "PodIP",
    "PodOS",
    "PodReadinessGate",
    "PodResourceClaim",
    "PodResourceClaimStatus",
    "PodSchedulingGate",
    "PodSecurityContext",
    "PodSpec",
    "PodStatus",
    "PortworxVolumeSource",
    "PreferredSchedulingTerm",
    "Probe",
    "ProjectedVolumeSource",
    "Quantity",
    "QuobyteVolumeSource",
    "RBDVolumeSource",
    "ResourceClaim",
    "ResourceFieldSelector",
    "ResourceRequirements",
    "SELinuxOptions",
    "ScaleIOVolumeSource",
    "SeccompProfile",
    "SecretEnvSource",
    "SecretKeySelector",
    "SecretProjection",
    "SecretVolumeSource",
    "SecurityContext",
    "ServiceAccountTokenProjection",
    "SleepAction",
    "StorageOSVolumeSource",
    "Sysctl",
    "TCPSocketAction",
    "Time",
    "Toleration",
    "TopologySpreadConstraint",
    "TypedLocalObjectReference",
    "TypedObjectReference",
    "Volume",
    "VolumeDevice",
    "VolumeMount",
    "VolumeMountStatus",
    "VolumeProjection",
    "VolumeResourceRequirements",
    "VsphereVirtualDiskVolumeSource",
    "WeightedPodAffinityTerm",
    "WindowsSecurityContextOptions",
]
