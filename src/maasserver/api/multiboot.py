"""
Multi-boot mixin for MAAS MachineHandler.

Provides API operations for managing multi-boot partition layouts.

Maps to: src/maasserver/api/multiboot_mixin.py

All helper logic is delegated to module-level functions in
``maasserver.multiboot_helpers``, following the MAAS convention
(see preseed.py, preseed_network.py, preseed_storage.py).
"""

__all__ = [
    "MultiBootMixin",
]

import logging

from maasserver.api.support import operation
from maasserver.enum import NodePermission, NODE_STATUS
from maasserver.exceptions import (
    MAASAPIBadRequest,
    MAASAPIValidationError,
    NodeStateViolation,
    PermissionDenied,
)
from maasserver.forms.machine import MachineForm
from maasserver.models.node import Node
from maasserver.models.nodemetadata import NodeMetadata
from maasserver.node_status import NODE_STATUS_CHOICES_DICT, NODE_TRANSITIONS
from maasserver.utils.orm import locks
from maasserver.multiboot_deploy import (
    compose_os_config,
    delete_layout,
    generate_multi_boot_installer,
    load_layout,
    read_layout_from_request,
    store_layout,
    validate_layout,
)

maaslog = logging.getLogger("maas")


class MultiBootMixin:
    """Mixin that adds multi-boot operations to MachineHandler.

    Usage
    -----
    class MachineHandler(
        MultiBootMixin,
        NodeHandler,
        WorkloadAnnotationsMixin,
        PowerMixin,
    ):
        ...

    Provides four API operations (set-layout, get-layout, delete-layout,
    multi-boot-deploy) and a public ``multi_boot()`` accessor for the
    ``DISPLAYED_MACHINE_FIELDS`` tuple.
    """

    @classmethod
    def multi_boot(handler, node) -> bool:
        """Return True if this node has a multi-boot layout configured.

        Used by ``DISPLAYED_MACHINE_FIELDS`` to expose the ``multi_boot``
        boolean in machine list output.
        """
        return load_layout(node) is not None

    # ──
    # API operations
    # ──

    @operation(idempotent=False)
    def set_layout(self, request, system_id) -> Node:
        """@description-title Set multi-boot partition layout
        @description Upload a YAML or JSON file defining the multi-boot
        partition layout and operating system entries. Replaces any
        existing layout for this machine.

        @param (string) "{system_id}" [required=true] The machine's
        system_id.
        @param (file) "layout" [required=true] YAML or JSON file
        describing the partition layout for each OS.

        @success (http-status-code) "200" 200
        @error (http-status-code) "404" 404
        @error (content) "not-found" The requested node is not found.
        @error (http-status-code) "403" 403
        @error (content) "no-perms" The user does not have permission.
        """
        machine = self.model.objects.get_node_or_404(
            system_id=system_id,
            user=request.user,
            perm=NodePermission.edit,
        )
        if not request.user.has_perm(NodePermission.edit, machine):
            raise PermissionDenied()
        layout_data = read_layout_from_request(request)
        validate_layout(layout_data)
        store_layout(machine, layout_data)
        return machine

    @operation(idempotent=True)
    def get_layout(self, request, system_id) -> dict:
        """@description-title Get multi-boot partition layout
        @description Return the currently stored multi-boot partition
        layout for this machine.

        @param (string) "{system_id}" [required=true] The machine's
        system_id.

        @success (http-status-code) "200" 200
        @error (http-status-code) "404" 404
        @error (content) "not-found" The requested node is not found.
        @error (http-status-code) "403" 403
        @error (content) "no-perms" The user does not have permission.
        """
        machine = self.model.objects.get_node_or_404(
            system_id=system_id,
            user=request.user,
            perm=NodePermission.view,
        )
        if not request.user.has_perm(NodePermission.view, machine):
            raise PermissionDenied()
        layout = load_layout(machine)
        if layout is None:
            raise MAASAPIBadRequest(
                "No multi-boot layout configured for this machine."
            )
        return layout

    @operation(idempotent=False)
    def delete_layout(self, request, system_id) -> Node:
        """@description-title Delete multi-boot partition layout
        @description Remove the multi-boot partition layout from this
        machine, reverting it to standard single-OS deployment.

        @param (string) "{system_id}" [required=true] The machine's
        system_id.

        @success (http-status-code) "200" 200
        @error (http-status-code) "404" 404
        @error (content) "not-found" The requested node is not found.
        @error (http-status-code) "403" 403
        @error (content) "no-perms" The user does not have permission.
        """
        machine = self.model.objects.get_node_or_404(
            system_id=system_id,
            user=request.user,
            perm=NodePermission.edit,
        )
        if not request.user.has_perm(NodePermission.edit, machine):
            raise PermissionDenied()
        delete_layout(machine)
        return machine

    @operation(idempotent=False)
    def multi_boot_deploy(self, request, system_id) -> Node:
        """@description-title Deploy multiple operating systems
        @description Deploy this machine with multiple operating systems
        as configured by set-layout. The machine must have a valid
        multi-boot layout stored.

        @param (string) "{system_id}" [required=true] The machine's
        system_id.

        @success (http-status-code) "200" 200
        @error (http-status-code) "404" 404
        @error (content) "not-found" The requested node is not found.
        @error (http-status-code) "403" 403
        @error (content) "no-perms" The user does not have permission.
        @error (http-status-code) "409" 409
        @error (content) "state-violation" The machine is not in a
        deployable state.
        @error (http-status-code) "400" 400
        @error (content) "no-layout" No multi-boot layout configured
        for this machine.
        """
        # --- Permission checks (mirrors deploy()) ---
        machine = self.model.objects.get_node_or_404(
            system_id=system_id,
            user=request.user,
            perm=NodePermission.edit,
        )
        if not request.user.has_perm(NodePermission.edit, machine):
            raise PermissionDenied()

        # --- Acquire (mirrors deploy()) ---
        if machine.status == NODE_STATUS.READY:
            with locks.node_acquire:
                if machine.owner is not None and machine.owner != request.user:
                    raise NodeStateViolation(
                        "Can't allocate a machine belonging to another user."
                    )
                maaslog.info(
                    "Request from user %s to acquire machine: %s (%s)",
                    request.user.username,
                    machine.fqdn,
                    machine.system_id,
                )
                machine.acquire(request.user)

        # --- State check (mirrors deploy()) ---
        if NODE_STATUS.DEPLOYING not in NODE_TRANSITIONS[machine.status]:
            raise NodeStateViolation(
                "Can't deploy a machine that is in the '%s' state"
                % NODE_STATUS_CHOICES_DICT[machine.status]
            )

        # --- Load and validate layout ---
        layout = load_layout(machine)
        if layout is None:
            raise MAASAPIBadRequest(
                "No multi-boot layout configured for this machine."
            )
        validate_layout(layout)

        # --- Generate per-OS curtin configs and embed in wrapper script ---
        os_configs = []
        for i, os_entry in enumerate(layout["oses"]):
            config = compose_os_config(request, machine, os_entry, i)
            os_configs.append(config)

        script = generate_multi_boot_installer(
            layout, machine, os_configs
        )
        NodeMetadata.objects.update_or_create(
            node=machine, key="multi_boot_preseed",
            defaults={"value": script},
        )

        # --- Form init (empty data — layout drives everything) ---
        form = MachineForm(instance=machine, data={})
        if form.is_valid():
            form.save()
        else:
            raise MAASAPIValidationError(form.errors)

        # --- Power on (mirrors deploy()) ---
        return self.power_on(request, system_id)

