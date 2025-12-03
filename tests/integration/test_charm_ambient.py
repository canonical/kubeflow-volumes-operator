# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from charmed_kubeflow_chisme.testing import (
    assert_logging,
    assert_path_reachable_through_ingress,
    deploy_and_assert_grafana_agent,
    deploy_and_integrate_service_mesh_charms,
)
from pytest_operator.plugin import OpsTest

log = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CONFIG_MAP = "volumes-web-app-viewer-spec-ck6bhh4bdm"
CHARM_NAME = METADATA["name"]
HEADERS = {
    "kubeflow-userid": "",
}
HTTP_PATH = "/volumes"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    my_charm = await ops_test.build_charm(".")
    image_path = METADATA["resources"]["oci-image"]["upstream-source"]

    await ops_test.model.deploy(my_charm, resources={"oci-image": image_path}, trust=True)

    await ops_test.model.wait_for_idle(
        [CHARM_NAME],
        wait_for_active=True,
        raise_on_blocked=True,
        raise_on_error=True,
        timeout=300,
    )

    # Deploying grafana-agent-k8s and add all relations
    await deploy_and_assert_grafana_agent(
        ops_test.model, CHARM_NAME, metrics=False, dashboard=False, logging=True
    )


@pytest.mark.abort_on_fail
async def test_deploy_and_relate_dependencies(ops_test: OpsTest):
    await deploy_and_integrate_service_mesh_charms(CHARM_NAME, ops_test.model)

    # Commenting out kubeflow-dashboard and kubeflow-profiles deployment and relation
    # until they are integrated with ambient
    # TODO uncomment when https://github.com/canonical/kubeflow-dashboard-operator/issues/303
    # and https://github.com/canonical/kubeflow-profiles-operator/issues/272 are closed
    #
    # await ops_test.model.deploy(
    #     KUBEFLOW_DASHBOARD.charm,
    #     channel=KUBEFLOW_DASHBOARD.channel,
    #     trust=KUBEFLOW_DASHBOARD.trust,
    # )
    # await ops_test.model.deploy(
    #     KUBEFLOW_PROFILES.charm,
    #     channel=KUBEFLOW_PROFILES.channel,
    #     trust=KUBEFLOW_PROFILES.trust,
    # )

    # await ops_test.model.integrate(KUBEFLOW_DASHBOARD.charm, KUBEFLOW_PROFILES.charm)
    # await ops_test.model.integrate(
    #     f"{ISTIO_INGRESS_K8S.charm}:istio-ingress-route",
    #     f"{KUBEFLOW_DASHBOARD.charm}:istio-ingress-route"
    # )
    # await ops_test.model.integrate(f"{ISTIO_BEACON_K8S.charm}:service-mesh",
    # f"{KUBEFLOW_DASHBOARD.charm}:service-mesh")

    # await ops_test.model.integrate(f"{KUBEFLOW_DASHBOARD.charm}:dashboard-links",
    # f"{CHARM_NAME}:dashboard-links")

    # raise_on_blocked=False to avoid flakiness due to kubeflow-dashboard going to
    # Blocked((install) Add required relation to kubeflow-profiles) although it has been added


async def test_logging(ops_test: OpsTest):
    """Test logging is defined in relation data bag."""
    app = ops_test.model.applications[CHARM_NAME]
    await assert_logging(app)


@pytest.mark.abort_on_fail
async def test_ui_is_accessible(ops_test: OpsTest):
    """Verify that UI is accessible through the ingress gateway."""
    await assert_path_reachable_through_ingress(
        http_path=HTTP_PATH,
        namespace=ops_test.model.name,
        headers=HEADERS,
        expected_content_type="text/html",
    )
