"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

ISTIO_GATEWAY = CharmSpec(
    charm="istio-gateway", channel="latest/edge", config={"kind": "ingress"}, trust=True
)
ISTIO_PILOT = CharmSpec(
    charm="istio-pilot",
    channel="latest/edge",
    config={"default-gateway": "kubeflow-gateway"},
    trust=True,
)
ISTIO_K8S = CharmSpec(charm="istio-k8s", channel="2/edge", trust=True)
ISTIO_INGRESS_K8S = CharmSpec(
    charm="istio-ingress-k8s",
    channel="2/edge",
    trust=True,
)
ISTIO_BEACON_K8S = CharmSpec(
    charm="istio-beacon-k8s",
    channel="2/edge",
    trust=True,
)
KUBEFLOW_DASHBOARD = CharmSpec(charm="kubeflow-dashboard", channel="latest/edge", trust=True)
KUBEFLOW_PROFILES = CharmSpec(charm="kubeflow-profiles", channel="latest/edge", trust=True)
