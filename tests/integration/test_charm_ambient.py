# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import tenacity
import yaml
from charmed_kubeflow_chisme.testing import (
    ISTIO_INGRESS_K8S_APP,
    ISTIO_INGRESS_ROUTE_ENDPOINT,
    assert_logging,
    assert_path_reachable_through_ingress,
    deploy_and_assert_grafana_agent,
    deploy_and_integrate_service_mesh_charms,
    integrate_with_service_mesh,
)
from charms_dependencies import KUBEFLOW_DASHBOARD, KUBEFLOW_PROFILES
from lightkube import Client
from lightkube.generic_resource import create_namespaced_resource
from pytest_operator.plugin import OpsTest

log = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CONFIG_MAP = "volumes-web-app-viewer-spec-ck6bhh4bdm"
CHARM_NAME = METADATA["name"]
HEADERS = {
    "kubeflow-userid": "",
}
HTTP_PATH = "/volumes"

# A second istio-ingress-k8s instance used to verify multiple-ingress support.
SECOND_INGRESS_APP = "istio-ingress-k8s-alt"
INGRESS_CHANNEL = "2/stable"
# Name of the HTTPRoute submitted by kubeflow-volumes (see AmbientIngressRequirerComponent).
INGRESS_ROUTE_NAME = "http-route"
# Gateway listener section for cleartext HTTP on port 80.
HTTP_SECTION_NAME = "http-80"
# Path matched by the kubeflow-volumes HTTPRoute.
INGRESS_ROUTE_PATH = HTTP_PATH
# Gateway API generic resources, resolved at runtime via lightkube.
HTTPROUTE_RESOURCE = create_namespaced_resource(
    "gateway.networking.k8s.io", "v1", "HTTPRoute", "httproutes"
)
GATEWAY_RESOURCE = create_namespaced_resource(
    "gateway.networking.k8s.io", "v1", "Gateway", "gateways"
)
RETRY_120_SECONDS = tenacity.Retrying(
    stop=tenacity.stop_after_delay(120),
    wait=tenacity.wait_fixed(2),
    reraise=True,
)


@pytest.fixture(scope="session")
def lightkube_client() -> Client:
    client = Client(field_manager=CHARM_NAME)
    return client


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, request):
    entity_url = (
        await ops_test.build_charm(".")
        if not (entity_url := request.config.getoption("--charm-path"))
        else entity_url
    )
    image_path = METADATA["resources"]["oci-image"]["upstream-source"]

    await ops_test.model.deploy(entity_url, resources={"oci-image": image_path}, trust=True)

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

    await ops_test.model.deploy(
        KUBEFLOW_DASHBOARD.charm,
        channel=KUBEFLOW_DASHBOARD.channel,
        trust=KUBEFLOW_DASHBOARD.trust,
    )
    await ops_test.model.deploy(
        KUBEFLOW_PROFILES.charm,
        channel=KUBEFLOW_PROFILES.channel,
        trust=KUBEFLOW_PROFILES.trust,
    )

    await ops_test.model.integrate(
        f"{KUBEFLOW_DASHBOARD.charm}:kubeflow-profiles",
        f"{KUBEFLOW_PROFILES.charm}:kubeflow-profiles",
    )
    await integrate_with_service_mesh(
        KUBEFLOW_DASHBOARD.charm, ops_test.model, relate_to_ingress_route_endpoint=True
    )

    await ops_test.model.integrate(
        f"{KUBEFLOW_DASHBOARD.charm}:links", f"{CHARM_NAME}:dashboard-links"
    )

    # raise_on_blocked=False to avoid flakiness due to kubeflow-dashboard going to
    # Blocked((install) Add required relation to kubeflow-profiles) although it has been added
    await ops_test.model.wait_for_idle(
        raise_on_blocked=False,
        raise_on_error=True,
        timeout=900,
    )


async def test_logging(ops_test: OpsTest):
    """Test logging is defined in relation data bag."""
    app = ops_test.model.applications[CHARM_NAME]
    await assert_logging(app)


async def assert_ui_is_accessible(ops_test: OpsTest):
    """Verify that UI is accessible through the ingress gateway."""
    await assert_path_reachable_through_ingress(
        http_path=HTTP_PATH,
        namespace=ops_test.model.name,
        headers=HEADERS,
        expected_content_type="text/html",
    )


@pytest.mark.abort_on_fail
async def test_ui_is_accessible(ops_test: OpsTest):
    """Verify that UI is accessible through the ingress gateway before the second ingress."""
    await assert_ui_is_accessible(ops_test)


@pytest.mark.abort_on_fail
async def test_deploy_and_relate_second_ingress(ops_test: OpsTest):
    """Deploy a second istio-ingress-k8s and relate it to kubeflow-volumes.

    kubeflow-volumes must accept more than one istio-ingress-route relation without
    erroring, so it should remain active after the second ingress is related.
    """
    await ops_test.model.deploy(
        ISTIO_INGRESS_K8S_APP,
        application_name=SECOND_INGRESS_APP,
        channel=INGRESS_CHANNEL,
        trust=True,
    )
    await ops_test.model.wait_for_idle(
        [SECOND_INGRESS_APP],
        raise_on_blocked=False,
        raise_on_error=False,
        wait_for_active=True,
        timeout=60 * 15,
    )

    await ops_test.model.integrate(
        f"{SECOND_INGRESS_APP}:{ISTIO_INGRESS_ROUTE_ENDPOINT}",
        f"{CHARM_NAME}:{ISTIO_INGRESS_ROUTE_ENDPOINT}",
    )
    await ops_test.model.wait_for_idle(
        [CHARM_NAME, SECOND_INGRESS_APP],
        status="active",
        raise_on_blocked=False,
        raise_on_error=False,
        timeout=60 * 10,
        idle_period=30,
    )

    assert ops_test.model.applications[CHARM_NAME].units[0].workload_status == "active"


async def test_httproute_attached_to_second_gateway(ops_test: OpsTest, lightkube_client: Client):
    """Verify the HTTPRoute for the second ingress is created and bound to its Gateway.

    The istio-ingress-k8s charm names each route
    ``{source_app}-{route_name}-httproute-{section}-{ingress_app}`` and binds it to a
    Gateway named after the ingress application via ``parentRefs``. We assert that the
    route created for the second ingress is attached to the *second* Gateway (not the
    first) and routes the kubeflow-volumes path to the kubeflow-volumes backend.
    """
    namespace = ops_test.model.name

    expected_route_name = (
        f"{CHARM_NAME}-{INGRESS_ROUTE_NAME}-httproute-{HTTP_SECTION_NAME}-{SECOND_INGRESS_APP}"
    )

    # The second Gateway should exist, named after the second ingress application.
    lightkube_client.get(GATEWAY_RESOURCE, name=SECOND_INGRESS_APP, namespace=namespace)

    # Retry to give the ingress charm time to reconcile the HTTPRoute resources.
    httproute = None
    for attempt in RETRY_120_SECONDS:
        with attempt:
            httproute = lightkube_client.get(
                HTTPROUTE_RESOURCE, name=expected_route_name, namespace=namespace
            )

    parent_refs = httproute.spec["parentRefs"]
    assert len(parent_refs) == 1
    # The route must be attached to the SECOND gateway, not the first.
    assert parent_refs[0]["name"] == SECOND_INGRESS_APP
    assert parent_refs[0]["sectionName"] == HTTP_SECTION_NAME

    # And it must route the kubeflow-volumes path to the kubeflow-volumes backend.
    rule = httproute.spec["rules"][0]
    assert rule["matches"][0]["path"]["value"] == INGRESS_ROUTE_PATH
    assert rule["backendRefs"][0]["name"] == CHARM_NAME


@pytest.mark.abort_on_fail
async def test_ui_is_accessible_after_second_ingress(ops_test: OpsTest):
    """Verify that UI is still accessible through the ingress gateway after the second ingress."""
    await assert_ui_is_accessible(ops_test)
