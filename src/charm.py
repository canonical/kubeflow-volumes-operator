#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for the Kubeflow Volumes.

https://github.com/canonical/kubeflow-volumes-operator
"""

import logging
from pathlib import Path

import lightkube
from charmed_kubeflow_chisme.components import (
    CharmReconciler,
    ContainerFileTemplate,
    KubernetesComponent,
    LeadershipGateComponent,
    SdiRelationBroadcasterComponent,
)
from charmed_kubeflow_chisme.kubernetes import create_charm_default_labels
from charms.kubeflow_dashboard.v0.kubeflow_dashboard_links import (
    DashboardLink,
    KubeflowDashboardLinksRequirer,
)
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.observability_libs.v1.kubernetes_service_patch import KubernetesServicePatch
from lightkube.models.core_v1 import ServicePort
from lightkube.resources.core_v1 import ServiceAccount
from lightkube.resources.rbac_authorization_v1 import ClusterRole, ClusterRoleBinding
from ops import CharmBase, main

from components.istio_ambient_requirer_component import AmbientIngressRequirerComponent
from components.istio_relations_conflict_detector import IstioRelationsConflictDetectorComponent
from components.pebble_components import KubeflowVolumesInputs, KubeflowVolumesPebbleService

logger = logging.getLogger(__name__)
TEMPLATES_PATH = Path("src/templates")
K8S_RESOURCE_FILES = [TEMPLATES_PATH / "auth_manifests.yaml.j2"]

CONFIG_YAML_TEMPLATE_FILE = TEMPLATES_PATH / "viewer-spec.yaml"

DASHBOARD_LINKS = [
    DashboardLink(
        text="Volumes",
        link="/volumes/",
        type="item",
        icon="device:storage",
        location="menu",
    )
]


class KubeflowVolumesOperator(CharmBase):
    """Charm for the Kubeflow Volumes Web App.

    https://github.com/canonical/kubeflow-volumes-operator
    """

    def __init__(self, *args):
        super().__init__(*args)

        # Storage
        self._container_name = next(iter(self.meta.containers))
        _container_meta = self.meta.containers[self._container_name]
        _storage_name = next(iter(_container_meta.mounts))
        self._storage_path = Path(_container_meta.mounts[_storage_name].location)

        # add links in kubeflow-dashboard sidebar
        self.kubeflow_dashboard_sidebar = KubeflowDashboardLinksRequirer(
            charm=self,
            relation_name="dashboard-links",
            dashboard_links=DASHBOARD_LINKS,
        )

        # expose web app's port
        http_port = ServicePort(int(self.model.config["port"]), name="http")
        self.service_patcher = KubernetesServicePatch(
            self, [http_port], service_name=f"{self.model.app.name}"
        )

        # Charm logic
        self.charm_reconciler = CharmReconciler(self)
        self.leadership_gate = self.charm_reconciler.add(
            component=LeadershipGateComponent(
                charm=self,
                name="leadership-gate",
            ),
            depends_on=[],
        )

        self.kubernetes_resources = self.charm_reconciler.add(
            component=KubernetesComponent(
                charm=self,
                name="kubernetes:auth",
                resource_templates=K8S_RESOURCE_FILES,
                krh_resource_types={ClusterRole, ClusterRoleBinding, ServiceAccount},
                krh_labels=create_charm_default_labels(
                    self.app.name, self.model.name, scope="auth"
                ),
                context_callable=lambda: {"app_name": self.app.name, "namespace": self.model.name},
                lightkube_client=lightkube.Client(),
            ),
            depends_on=[self.leadership_gate],
        )

        self.istio_relations_conflict_detector = self.charm_reconciler.add(
            component=IstioRelationsConflictDetectorComponent(
                charm=self,
                name="istio-relations-conflict-detector",
                sidecar_relation_name="ingress",
                ambient_relation_name="istio-ingress-route",
            ),
            depends_on=[self.leadership_gate],
        )

        self.ambient_ingress_relation = self.charm_reconciler.add(
            component=AmbientIngressRequirerComponent(
                charm=self,
                name="ambient_relation:istio-ingress-route",
                service_name=self.model.app.name,
                port=int(self.model.config["port"]),
                path_prefix="/volumes",
                url_rewrite="/",
            ),
            depends_on=[self.leadership_gate, self.istio_relations_conflict_detector],
        )

        self.sidecar_ingress_relation = self.charm_reconciler.add(
            component=SdiRelationBroadcasterComponent(
                charm=self,
                name="sidecar_relation:ingress",
                relation_name="ingress",
                data_to_send={
                    "prefix": "/volumes",
                    "rewrite": "/",
                    "service": self.model.app.name,
                    "port": int(self.model.config["port"]),
                },
            ),
            depends_on=[self.leadership_gate, self.istio_relations_conflict_detector],
        )

        self.kubeflow_volumes_container = self.charm_reconciler.add(
            component=KubeflowVolumesPebbleService(
                charm=self,
                name="container:kubeflow-volumes",
                container_name="kubeflow-volumes",
                service_name="kubeflow-volumes",
                files_to_push=[
                    ContainerFileTemplate(
                        source_template_path=CONFIG_YAML_TEMPLATE_FILE,
                        destination_path=self._storage_path / "viewer-spec.yaml",
                    ),
                ],
                inputs_getter=lambda: KubeflowVolumesInputs(
                    APP_SECURE_COOKIES=self.model.config["secure-cookies"],
                    BACKEND_MODE=self.model.config["backend-mode"],
                    VOLUME_VIEWER_IMAGE=self.model.config["volume-viewer-image"],
                ),
            ),
            depends_on=[
                self.leadership_gate,
                self.kubernetes_resources,
            ],
        )

        self.charm_reconciler.install_default_event_handlers()
        self._logging = LogForwarder(charm=self)


if __name__ == "__main__":
    main(KubeflowVolumesOperator)
