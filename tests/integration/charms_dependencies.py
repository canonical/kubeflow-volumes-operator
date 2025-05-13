"""Charms dependencies for tests."""

from charmed_kubeflow_chisme.testing import CharmSpec

ISTIO_GATEWAY = CharmSpec(
    charm="istio-gateway", channel="1.24/stable", config={"kind": "ingress"}, trust=True
)
ISTIO_PILOT = CharmSpec(
    charm="istio-pilot",
    channel="1.24/stable",
    config={"default-gateway": "kubeflow-gateway"},
    trust=True,
)
KUBEFLOW_DASHBOARD = CharmSpec(charm="kubeflow-dashboard", channel="1.10/stable", trust=True)
KUBEFLOW_PROFILES = CharmSpec(charm="kubeflow-profiles", channel="1.10/stable", trust=True)
