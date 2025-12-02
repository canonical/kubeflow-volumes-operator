# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
from unittest.mock import MagicMock, patch

import pytest
import yaml
from charmed_kubeflow_chisme.testing import add_sdi_relation_to_harness
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness

from charm import KubeflowVolumesOperator


@pytest.fixture
def harness():
    """Returns a Harness for the KubeflowVolumesOperator charm."""
    harness = Harness(KubeflowVolumesOperator)

    # set model name to avoid validation errors
    harness.set_model_name("kubeflow")

    # set leader by default
    harness.set_leader(True)

    yield harness

    harness.cleanup()


@pytest.fixture()
def mocked_kubernetes_service_patch(mocker):
    """Mocks the KubernetesServicePatch for the charm."""
    mocked_kubernetes_service_patch = mocker.patch(
        "charm.KubernetesServicePatch", lambda x, y, service_name: None
    )
    yield mocked_kubernetes_service_patch


@pytest.fixture()
def mocked_lightkube_client(mocker):
    """Mocks the Lightkube Client in charm.py, returning a mock instead."""
    mocked_lightkube_client = MagicMock()
    mocker.patch("charm.lightkube.Client", return_value=mocked_lightkube_client)
    yield mocked_lightkube_client


@pytest.fixture()
def mocked_istio_ingress_requirer(mocker):
    """Mocks the IstioIngressRouteRequirer to avoid UnauthorizedError during tests."""
    mocked_requirer = mocker.patch(
        "components.istio_ambient_requirer_component.IstioIngressRouteRequirer"
    )
    yield mocked_requirer


def render_ingress_data(service, port) -> dict:
    """Returns typical data for the ingress relation."""
    return {
        "prefix": "/volumes",
        "rewrite": "/",
        "service": service,
        "port": int(port),
    }


def test_log_forwarding(harness, mocked_lightkube_client, mocked_kubernetes_service_patch, mocked_istio_ingress_requirer):
    """Test LogForwarder initialization."""
    with patch("charm.LogForwarder") as mock_logging:
        harness.begin()
        mock_logging.assert_called_once_with(charm=harness.charm)


def test_not_leader(harness, mocked_lightkube_client, mocked_kubernetes_service_patch, mocked_istio_ingress_requirer):
    """Test when we are not the leader."""
    harness.set_leader(False)
    harness.begin_with_initial_hooks()
    # Assert that we are not Active, and that the leadership-gate is the cause.
    assert not isinstance(harness.charm.model.unit.status, ActiveStatus)
    assert harness.charm.model.unit.status.message.startswith("[leadership-gate]")


def test_kubernetes_created_method(
    harness, mocked_lightkube_client, mocked_kubernetes_service_patch, mocked_istio_ingress_requirer
):
    """Test whether we try to create Kubernetes resources when we have leadership."""
    # Arrange
    # Needed because kubernetes component will only apply to k8s if we are the leader
    harness.set_leader(True)
    harness.begin()

    # Need to mock the leadership-gate to be active, and the kubernetes auth component so that it
    # sees the expected resources when calling _get_missing_kubernetes_resources

    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.kubernetes_resources.component._get_missing_kubernetes_resources = MagicMock(
        return_value=[]
    )

    # Act
    harness.charm.on.install.emit()

    # Assert
    assert mocked_lightkube_client.apply.call_count == 6
    assert isinstance(harness.charm.kubernetes_resources.status, ActiveStatus)


def test_ambient_ingress_component_active(
    harness, mocked_lightkube_client, mocked_kubernetes_service_patch, mocked_istio_ingress_requirer
):
    """Test that the ambient ingress component goes active when leadership gate is active."""
    # Arrange
    harness.set_leader(True)
    harness.begin()

    # Mock leadership_gate to be active
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    # Act
    harness.charm.on.install.emit()

    # Assert
    assert isinstance(harness.charm.ambient_ingress_relation.status, ActiveStatus)
    # Verify that submit_config was called
    mocked_istio_ingress_requirer.return_value.submit_config.assert_called()


def test_ambient_ingress_component_blocked_on_error(
    harness, mocked_lightkube_client, mocked_kubernetes_service_patch, mocked_istio_ingress_requirer
):
    """Test that the ambient ingress component goes blocked if config submission fails."""
    # Arrange
    harness.set_leader(True)
    harness.begin()

    # Mock leadership_gate to be active
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())
    
    # Mock submit_config to raise an exception
    mocked_istio_ingress_requirer.return_value.submit_config.side_effect = Exception("Test error")

    # Act
    harness.charm.on.install.emit()

    # Assert
    status = harness.charm.ambient_ingress_relation.status
    assert isinstance(status, BlockedStatus)
    assert "Failed to submit ingress config" in status.message
    assert "Test error" in status.message


def test_ingress_relation_with_related_app(
    harness, mocked_lightkube_client, mocked_kubernetes_service_patch, mocked_istio_ingress_requirer
):
    """Test that the kubeflow-volumes relation sends data to related apps and goes Active."""
    # Arrange
    harness.set_leader(True)  # needed to write to an SDI relation
    harness.begin()

    # Mock:
    # * leadership_gate to be active and executed
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())

    expected_relation_data = {
        "_supported_versions": ["v1"],
        "data": render_ingress_data(
            service=harness.model.app.name, port=harness.model.config["port"]
        ),
    }

    # Act
    # Add one relation with data.  This should trigger a charm reconciliation due to
    # relation-changed.
    relation_metadata = add_sdi_relation_to_harness(harness, "ingress", other_app="o1", data={})
    relation_ids_to_assert = [relation_metadata.rel_id]

    # Assert
    assert isinstance(harness.charm.sidecar_ingress_relation.status, ActiveStatus)
    assert_relation_data_send_as_expected(harness, expected_relation_data, relation_ids_to_assert)


def assert_relation_data_send_as_expected(harness, expected_relation_data, rel_ids_to_assert):
    """Asserts that we have sent the expected data to the given relations."""
    # Assert on the data we sent out to the other app for each relation.
    for rel_id in rel_ids_to_assert:
        relation_data = harness.get_relation_data(rel_id, harness.model.app)
        assert (
            yaml.safe_load(relation_data["_supported_versions"])
            == expected_relation_data["_supported_versions"]
        )
        assert yaml.safe_load(relation_data["data"]) == expected_relation_data["data"]


def test_pebble_services_running(
    harness, mocked_lightkube_client, mocked_kubernetes_service_patch, mocked_istio_ingress_requirer
):
    """Test that if the Kubernetes Component is Active, the pebble services successfully start."""
    # Arrange
    harness.begin()
    harness.set_can_connect("kubeflow-volumes", True)

    # Mock:
    # * leadership_gate to have get_status=>Active
    # * kubernetes_resources to have get_status=>Active
    harness.charm.leadership_gate.get_status = MagicMock(return_value=ActiveStatus())
    harness.charm.kubernetes_resources.get_status = MagicMock(return_value=ActiveStatus())

    # Act
    harness.charm.on.install.emit()

    # Assert
    container = harness.charm.unit.get_container("kubeflow-volumes")
    service = container.get_service("kubeflow-volumes")
    assert service.is_running()
    # Assert the environment variables that are set from inputs are correctly applied
    environment = container.get_plan().services["kubeflow-volumes"].environment
    assert (
        environment["APP_SECURE_COOKIES"]
        == str(harness.charm.config.get("secure-cookies")).lower()
    )
    assert environment["BACKEND_MODE"] == harness.charm.config.get("backend-mode")
    assert environment["VOLUME_VIEWER_IMAGE"] == harness.charm.config.get("volume-viewer-image")


def test_istio_relations_conflict_detector_no_relations(
    harness, mocked_lightkube_client, mocked_kubernetes_service_patch, mocked_istio_ingress_requirer
):
    """Test conflict detector when no relations are present."""
    # Arrange & Act
    harness.begin()
    
    # Assert
    assert isinstance(harness.charm.istio_relations_conflict_detector.component.get_status(), ActiveStatus)


def test_istio_relations_conflict_detector_only_ambient(
    harness, mocked_lightkube_client, mocked_kubernetes_service_patch, mocked_istio_ingress_requirer
):
    """Test conflict detector when only ambient relation is present."""
    # Arrange
    harness.begin()
    
    # Act - Add only ambient relation
    harness.add_relation("istio-ingress-route", "istio-ingress")
    
    # Assert
    assert isinstance(harness.charm.istio_relations_conflict_detector.component.get_status(), ActiveStatus)


def test_istio_relations_conflict_detector_only_sidecar(
    harness, mocked_lightkube_client, mocked_kubernetes_service_patch, mocked_istio_ingress_requirer
):
    """Test conflict detector when only sidecar relation is present."""
    # Arrange
    harness.begin()
    
    # Act - Add only sidecar relation
    harness.add_relation("ingress", "istio-pilot")
    
    # Assert
    assert isinstance(harness.charm.istio_relations_conflict_detector.component.get_status(), ActiveStatus)


def test_istio_relations_conflict_detector_both_relations(
    harness, mocked_lightkube_client, mocked_kubernetes_service_patch, mocked_istio_ingress_requirer
):
    """Test conflict detector when both relations are present - should be blocked."""
    # Arrange
    harness.begin()
    
    # Act - Add both relations
    harness.add_relation("istio-ingress-route", "istio-ingress")
    harness.add_relation("ingress", "istio-pilot")
    
    # Assert
    status = harness.charm.istio_relations_conflict_detector.component.get_status()
    assert isinstance(status, BlockedStatus)
    assert "Cannot have both" in status.message
    assert "istio-ingress-route" in status.message
    assert "ingress" in status.message
