# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from charmed_kubeflow_chisme.testing import assert_logging, deploy_and_assert_grafana_agent
from charms_dependencies import ISTIO_GATEWAY, ISTIO_PILOT, KUBEFLOW_DASHBOARD, KUBEFLOW_PROFILES
from pytest_operator.plugin import OpsTest

# from random import choices
# from string import ascii_lowercase
# from subprocess import check_output
# from time import sleep
# from lightkube import Client

# from selenium.common.exceptions import JavascriptException, WebDriverException
# from selenium.webdriver.firefox.options import Options
# from selenium.webdriver.support.ui import WebDriverWait
# from seleniumwire import webdriver

log = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
CONFIG_MAP = "volumes-web-app-viewer-spec-ck6bhh4bdm"
CHARM_NAME = METADATA["name"]
ISTIO_GATEWAY_APP_NAME = "istio-ingressgateway"

# @pytest.fixture(scope="session")
# def lightkube_client() -> Client:
#     client = Client(field_manager=CHARM_NAME)
#     return client


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
async def test_relate_dependencies(ops_test: OpsTest):
    await ops_test.model.deploy(
        ISTIO_PILOT.charm,
        channel=ISTIO_PILOT.channel,
        config=ISTIO_PILOT.config,
        trust=ISTIO_PILOT.trust,
    )

    await ops_test.model.deploy(
        ISTIO_GATEWAY.charm,
        application_name=ISTIO_GATEWAY_APP_NAME,
        channel=ISTIO_GATEWAY.channel,
        config=ISTIO_GATEWAY.config,
        trust=ISTIO_GATEWAY.trust,
    )
    await ops_test.model.integrate(
        f"{ISTIO_PILOT.charm}:istio-pilot", f"{ISTIO_GATEWAY_APP_NAME}:istio-pilot"
    )

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

    await ops_test.model.integrate(KUBEFLOW_DASHBOARD.charm, KUBEFLOW_PROFILES.charm)
    await ops_test.model.integrate(
        f"{ISTIO_PILOT.charm}:ingress", f"{KUBEFLOW_DASHBOARD.charm}:ingress"
    )
    await ops_test.model.integrate(ISTIO_PILOT.charm, CHARM_NAME)
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


# # Disabled until we re-enable the selenium tests below
# @pytest.fixture()
# def profile(lightkube_client):
#     """Creates a Profile object in cluster, cleaning it up after"""
#     profile_file = "./tests/integration/profile.yaml"
#     krh = KubernetesResourceHandler(
#         field_manager="volumes-ci",
#         template_files=[profile_file],
#         context={},
#     )
#     # Syntax here might be wrong - needs to be tested when these tests are re-enabled
#     yaml_rendered = hrh.render_manifests()
#     profilename = yaml_rendered["metadata"]["name"]
#
#     krh.apply()
#     yield profilename
#
#     # TODO: Delete the profile object using the above rendered yaml


# Disabled until we re-enable the selenium tests below
# When reenabling, we should add Service to "from lightkube.resources.core_v1 import"
# @pytest.fixture()
# def driver(request, ops_test, profile):
#     profile_name = profile
#     lightkube_client = Client()
#     gateway_svc = lightkube_client.get(
#         Service, "istio-ingressgateway-workload", namespace=ops_test.model_name
#     )
#
#     endpoint = gateway_svc.status.loadBalancer.ingress[0].ip
#     url = f"http://{endpoint}.nip.io/_/volumes/?ns={profile_name}"
#
#     options = Options()
#     options.headless = True
#     options.log.level = "trace"
#
#     kwargs = {
#         "options": options,
#         "seleniumwire_options": {"enable_har": True},
#     }
#
#     with webdriver.Firefox(**kwargs) as driver:
#         wait = WebDriverWait(driver, 15, 1, (JavascriptException, StopIteration))
#         for _ in range(60):
#             try:
#                 driver.get(url)
#                 break
#             except WebDriverException:
#                 sleep(5)
#         else:
#             driver.get(url)
#
#         yield driver, wait, url
#
#         Path(f"/tmp/selenium-{request.node.name}.har").write_text(driver.har)
#         driver.get_screenshot_as_file(f"/tmp/selenium-{request.node.name}.png")


# TODO: Re-enable tests - Temporarily disabled.  They work locally, but not in CI
# TODO: v1.6 removed the #newResource ID from the button we want to click.  Need
#       to access it another way
#
# def test_first_access_to_ui(driver):
#     """Access volumes page once for everything to be initialized correctly"""
#
#     driver, wait, url = driver
#
#     # Click "New Volume" button
#     script = fix_queryselector(["main-page", "iframe-container", "iframe"])
#     script += ".contentWindow.document.body.querySelector('#newResource')"
#     wait.until(lambda x: x.execute_script(script))
#     driver.execute_script(script + ".click()")
#
#
# def test_volume(driver):
#     """Ensures a volume can be created and deleted."""
#
#     driver, wait, url = driver
#
#     volume_name = "ci-test-" + "".join(choices(ascii_lowercase, k=10))
#
#     # Click "New Volume" button
#     script = fix_queryselector(["main-page", "iframe-container", "iframe"])
#     script += ".contentWindow.document.body.querySelector('#newResource')"
#     wait.until(lambda x: x.execute_script(script))
#     driver.execute_script(script + ".click()")
#
#     # Enter volume name
#     script = fix_queryselector(["main-page", "iframe-container", "iframe"])
#     script += (
#         ".contentWindow.document.body.querySelector('input[placeholder=\"Name\"]')"
#     )
#     wait.until(lambda x: x.execute_script(script))
#     driver.execute_script(script + '.value = "%s"' % volume_name)
#     driver.execute_script(script + '.dispatchEvent(new Event("input"))')
#
#     # Click submit on the form. Sleep for 1 second before clicking the submit
#     # button due to animations.
#     script = fix_queryselector(["main-page", "iframe-container", "iframe"])
#     script += ".contentWindow.document.body.querySelector('form')"
#     wait.until(lambda x: x.execute_script(script))
#     driver.execute_script(script + '.dispatchEvent(new Event("ngSubmit"))')
#
#     # doc points at the nested Document hidden in all of the shadowroots
#     # Saving as separate variable to make constructing `Document.evaluate`
#     # query easier, as that requires `contextNode` to be equal to `doc`.
#     doc = fix_queryselector(["main-page", "iframe-container", "iframe"])[7:]
#     doc += ".contentWindow.document"
#
#     # Since upstream doesn't use proper class names or IDs or anything, find the
#     # <tr> containing elements that contain the notebook name and `ready`, signifying
#     # that the notebook is finished booting up. Returns a reference to the containing
#     # <tr> element.
#     chonky_boi = "/".join(
#         [
#             f"//*[contains(text(), '{volume_name}')]",
#             "ancestor::tr",
#             "/*[contains(@class, 'ready')]",
#             "ancestor::tr",
#         ]
#     )
#
#     script = evaluate(doc, chonky_boi)
#     wait.until(lambda x: x.execute_script(script))
#
#     # Delete volumes and wait for it to finalize
#     driver.execute_script(evaluate(doc, "//*[contains(text(), 'delete')]") + ".click()")
#     driver.execute_script(
#         f"{doc}.body.querySelector('.mat-dialog-container .mat-warn').click()"
#     )
#
#     script = evaluate(doc, "//*[contains(text(), '{volume_name}')]")
#     wait.until_not(lambda x: x.execute_script(script))


# def evaluate(doc, xpath):
#     result_type = "XPathResult.FIRST_ORDERED_NODE_TYPE"
#     return f'return {doc}.evaluate("{xpath}", {doc}, null, {result_type}, null).singleNodeValue'


# def fix_queryselector(elems):
#     """Workaround for web components breaking querySelector."""

#     selectors = '").shadowRoot.querySelector("'.join(elems)
#     return 'return document.querySelector("' + selectors + '")'
