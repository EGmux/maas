"""
Standalone helper functions for multi-boot deployment.

Maps to: src/maasserver/multiboot_deploy.py (NEW)

Follows the MAAS convention of module-level functions (see preseed.py,
preseed_network.py, preseed_storage.py).
"""

__all__ = [
    "read_layout_from_request",
    "validate_layout",
    "validate_os_entry",
    "validate_partition",
    "compose_os_config",
    "load_layout",
    "store_layout",
    "delete_layout",
    "generate_multi_boot_installer",
]

import yaml
from typing import Optional
import logging

from django.db import transaction

from maasserver.enum import NODE_STATUS
from maasserver.exceptions import (
    MAASAPIBadRequest,
    MAASAPIValidationError,
)
from maasserver.models.node import Node
from maasserver.models.nodemetadata import NodeMetadata
from maasserver.models.multiboot import (
    MultiBootDeployment,
    MultiBootOS,
    MultiBootPartition,
)
from maasserver.models.physicalblockdevice import PhysicalBlockDevice
from maasserver.preseed import get_curtin_merged_config
from maasserver.node_status import NODE_STATUS_CHOICES_DICT, NODE_TRANSITIONS

maaslog = logging.getLogger("maas")


# ── Canonical layout key names ──

_BOOT_KEY = "boot"
_OSES_KEY = "oses"
_DEFAULT_KEY = "default"
_TIMEOUT_KEY = "timeout"
_OSYSTEM_KEY = "osystem"
_DISTRO_SERIES_KEY = "distro_series"
_HWE_KERNEL_KEY = "hwe_kernel"
_ARCHITECTURE_KEY = "architecture"
_DISK_KEY = "disk"
_PARTITIONS_KEY = "partitions"
_SIZE_KEY = "size"
_FSTYPE_KEY = "fstype"
_MOUNT_POINT_KEY = "mount_point"

# NodeMetadata key for the generated wrapper script
_MULTI_BOOT_PRESEED_KEY = "multi_boot_preseed"

# Minimum number of OS entries required
_MIN_OS_COUNT = 2

# Allowed filesystem types for partitions
_ALLOWED_FSTYPES = {"ext4", "ext3", "ext2", "xfs", "btrfs", "fat32", "fat16", "ntfs", "swap"}


def read_layout_from_request(request) -> dict:
    """Extract the layout dict from an HTTP request.

    Supports both file upload (multipart) and raw POST body.

    Parameters
    ----------
    request : HttpRequest

    Returns
    -------
    dict
        Parsed layout data.

    Raises
    ------
    MAASAPIBadRequest
        If no layout is provided or the content cannot be parsed.
    """
    # 1. Try request.data (file upload)
    layout_file = request.data.get("layout")
    if layout_file is not None:
        try:
            raw = layout_file.read()
            return yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise MAASAPIBadRequest(
                "Invalid YAML: %s" % exc
            )

    # 2. Try request.POST (raw string)
    raw = request.POST.get("layout")
    if raw is not None:
        try:
            return yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise MAASAPIBadRequest(
                "Invalid YAML: %s" % exc
            )

    raise MAASAPIBadRequest("No layout file provided.")


def validate_layout(layout_data: dict) -> None:
    """Validate layout structure.

    Checks the canonical dict conforms to the schema defined
    in section 4.3 of the interfaces document.

    Parameters
    ----------
    layout_data : dict
        The layout dict to validate.

    Raises
    ------
    MAASAPIValidationError
        On the first validation failure (see section 4.3 for full list).
    """
    # 1. Must be a dict
    if not isinstance(layout_data, dict):
        raise MAASAPIValidationError("Layout must be a dict.")

    # 2. Must contain "boot" key
    if _BOOT_KEY not in layout_data:
        raise MAASAPIValidationError(
            "Layout must contain a '%s' key." % _BOOT_KEY
        )

    # 3. Must contain "oses" key
    if _OSES_KEY not in layout_data:
        raise MAASAPIValidationError(
            "Layout must contain an '%s' key." % _OSES_KEY
        )

    boot = layout_data[_BOOT_KEY]
    oses = layout_data[_OSES_KEY]

    # 4. "oses" must be a list
    if not isinstance(oses, list):
        raise MAASAPIValidationError(
            "'%s' must be a list, got %s." % (_OSES_KEY, type(oses).__name__)
        )

    # 5. "oses" must have >= 2 entries
    if len(oses) < _MIN_OS_COUNT:
        raise MAASAPIValidationError(
            "'%s' must contain at least %d entries, got %d."
            % (_OSES_KEY, _MIN_OS_COUNT, len(oses))
        )

    # 6. Validate boot config
    if not isinstance(boot, dict):
        raise MAASAPIValidationError(
            "'%s' must be a dict, got %s." % (_BOOT_KEY, type(boot).__name__)
        )
    default_index = boot.get(_DEFAULT_KEY, 0)
    if not isinstance(default_index, int) or default_index < 0:
        raise MAASAPIValidationError(
            "'%s.%s' must be a non-negative integer."
            % (_BOOT_KEY, _DEFAULT_KEY)
        )
    if default_index >= len(oses):
        raise MAASAPIValidationError(
            "'%s.%s' (%d) is out of range for %d OS entries."
            % (_BOOT_KEY, _DEFAULT_KEY, default_index, len(oses))
        )
    timeout = boot.get(_TIMEOUT_KEY, 5)
    if not isinstance(timeout, int) or timeout < 0:
        raise MAASAPIValidationError(
            "'%s.%s' must be a non-negative integer."
            % (_BOOT_KEY, _TIMEOUT_KEY)
        )

    # 7. Validate each OS entry
    for i, os_entry in enumerate(oses):
        validate_os_entry(os_entry, i)


def validate_os_entry(os_entry: dict, index: int) -> None:
    """Validate a single OS entry within the layout.

    Parameters
    ----------
    os_entry : dict
        The OS entry to validate.
    index : int
        Position of this entry in the ``oses`` list (for error messages).

    Raises
    ------
    MAASAPIValidationError
        On the first validation failure.
    """
    prefix = "'oses[%d]'" % index

    # 7a. Must be a dict
    if not isinstance(os_entry, dict):
        raise MAASAPIValidationError(
            "%s must be a dict, got %s." % (prefix, type(os_entry).__name__)
        )

    # 7b. Must have "osystem"
    if _OSYSTEM_KEY not in os_entry:
        raise MAASAPIValidationError(
            "%s missing required key '%s'." % (prefix, _OSYSTEM_KEY)
        )

    # 7c. Must have "distro_series"
    if _DISTRO_SERIES_KEY not in os_entry:
        raise MAASAPIValidationError(
            "%s missing required key '%s'." % (prefix, _DISTRO_SERIES_KEY)
        )

    osystem = os_entry[_OSYSTEM_KEY]

    # 7d. Must have "partitions" dict
    if _PARTITIONS_KEY not in os_entry:
        raise MAASAPIValidationError(
            "%s missing required key '%s'." % (prefix, _PARTITIONS_KEY)
        )
    partitions = os_entry[_PARTITIONS_KEY]
    if not isinstance(partitions, dict):
        raise MAASAPIValidationError(
            "%s '%s' must be a dict, got %s."
            % (prefix, _PARTITIONS_KEY, type(partitions).__name__)
        )

    # 7e. partitions must contain at least "/"
    if "/" not in partitions:
        raise MAASAPIValidationError(
            "%s '%s' must contain a root partition ('/')."
            % (prefix, _PARTITIONS_KEY)
        )

    # 7f. Validate each partition
    for mount_point, part_config in partitions.items():
        validate_partition(part_config, mount_point, prefix, osystem)


def validate_partition(
    part_config, mount_point: str, os_prefix: str, osystem: str
) -> None:
    """Validate a single partition entry.

    Parameters
    ----------
    part_config : any
        The partition configuration value.
    mount_point : str
        The mount point key (e.g. "/", "/boot", "/boot/efi").
    os_prefix : str
        Prefix for error messages (e.g. "oses[0]").
    osystem : str
        The OS type of the parent entry (for ntfs validation).

    Raises
    ------
    MAASAPIValidationError
        On the first validation failure.
    """
    prefix = "%s '%s'['%s']" % (os_prefix, _PARTITIONS_KEY, mount_point)

    # 7f.i. partition config must be a dict
    if not isinstance(part_config, dict):
        raise MAASAPIValidationError(
            "%s must be a dict, got %s." % (prefix, type(part_config).__name__)
        )

    # 7f.ii. Must have "size"
    if _SIZE_KEY not in part_config:
        raise MAASAPIValidationError(
            "%s missing required key '%s'." % (prefix, _SIZE_KEY)
        )

    # 7f.iii. Must have "fstype"
    if _FSTYPE_KEY not in part_config:
        raise MAASAPIValidationError(
            "%s missing required key '%s'." % (prefix, _FSTYPE_KEY)
        )

    fstype = part_config[_FSTYPE_KEY]

    # 7f.iv. fstype must be in _ALLOWED_FSTYPES
    if fstype not in _ALLOWED_FSTYPES:
        raise MAASAPIValidationError(
            "%s '%s' unsupported fstype '%s'. "
            "Allowed: %s." % (prefix, _FSTYPE_KEY, fstype, _ALLOWED_FSTYPES)
        )

    # 7f.v. "ntfs" only allowed for windows OS entries
    if fstype == "ntfs" and osystem != "windows":
        raise MAASAPIValidationError(
            "%s fstype 'ntfs' is only supported for osystem 'windows', "
            "got '%s'." % (prefix, osystem)
        )


def compose_os_config(
    request, machine, os_entry: dict, index: int
) -> str:
    """Generate a single-OS curtin config for one entry in the layout.

    Calls MAAS's standard config composers with the per-OS parameters
    (osystem, distro_series, hwe_kernel) and strips the storage section
    since ``block-meta`` handles partitioning globally for all OSes
    in the multi-boot wrapper script.

    Parameters
    ----------
    request : HttpRequest
        The deploy request (passed through to standard composers).
    machine : Node
        The target machine.
    os_entry : dict
        One entry from the layout's ``oses`` list.
    index : int
        Position in the layout (for error messages / labeling).

    Returns
    -------
    str
        Complete curtin YAML config for this OS, minus storage.

    Raises
    ------
    MAASAPIValidationError
        If the standard curtin config cannot be rendered.
    """
    osystem = os_entry[_OSYSTEM_KEY]
    series = os_entry[_DISTRO_SERIES_KEY]

    # Temporarily override machine OS fields so get_curtin_merged_config
    # generates config for this specific OS entry instead of the
    # machine's default OS.
    old_osystem = machine.osystem
    old_series = machine.distro_series
    try:
        machine.osystem = osystem
        machine.distro_series = series
        merged = get_curtin_merged_config(request, machine)
    finally:
        machine.osystem = old_osystem
        machine.distro_series = old_series


    # Strip storage — block-meta handles partitioning globally
    # for all OSes in the multi-boot wrapper script.
    merged.pop("storage", None)

    return yaml.safe_dump(merged)


def load_layout(machine) -> Optional[dict]:
    """Read layout from models into the canonical dict format.

    Parameters
    ----------
    machine : Node
        The machine whose layout to load.

    Returns
    -------
    dict or None
        ``None`` if no layout is configured.
        Otherwise a dict with the ``boot`` and ``oses`` keys.
    """
    # TODO: Query MultiBootDeployment -> MultiBootOS -> MultiBootPartition
    #       and reconstruct the canonical dict.
    raise NotImplementedError


@transaction.atomic
def store_layout(node: Node, layout_data: dict) -> None:
    """Write layout dict into MultiBootDeployment + related models.

    Replaces any existing layout for this node atomically.

    Parameters
    ----------
    node : Node
        The machine to associate this layout with.
    layout_data : dict
        Canonical layout dict with ``boot`` and ``oses`` keys.
    """
    # TODO: Delete existing MultiBootDeployment if present.
    #       Create new MultiBootDeployment.
    #       For each OS entry, create MultiBootOS.
    #       For each partition in each OS, create MultiBootPartition.
    raise NotImplementedError


def generate_multi_boot_installer(
    layout: dict, machine, os_configs: list[str]
) -> str:
    """Generate the multi-boot wrapper script.

    The script orchestrates curtin N times — once per OS in the
    layout — in a single ephemeral environment session.

    Parameters
    ----------
    layout : dict
        Canonical layout dict with ``boot`` and ``oses``.
    machine : Node
        The machine (used to resolve image URLs, disk info).
    os_configs : list[str]
        Per-OS curtin YAML configs produced by ``compose_os_config()``.
        One per entry in ``layout["oses"]``, in the same order.

    Returns
    -------
    str
        The complete bash script. Stored in NodeMetadata and
        served verbatim by the metadata service at PXE time.
    """
    # TODO: Build a bash script that:
    #   - For each os_config in os_configs:
    #       - Write the YAML to /tmp/os<N>.yaml
    #       - Run: curtin extract --config /tmp/os<N>.yaml --target /target/os<N> <image-url>
    #       - Run: curtin curthooks --config /tmp/os<N>.yaml --target /target/os<N>
    #   - Install GRUB via curtin hook or manual grub-install
    #   - Call netboot_off via the metadata service
    #   Image URL resolved via get_curtin_installer_url() for each OS.
    #   Linux vs Windows branching: Windows uses dd- images, Linux uses extract.
    raise NotImplementedError


def delete_layout(machine: Node) -> None:
    """Delete all multi-boot data for a machine.

    Parameters
    ----------
    machine : Node
    """
    # TODO: Delete MultiBootDeployment (CASCADE handles OS + partitions).
    #       Delete all NodeMetadata with key "multi_boot_*".
    raise NotImplementedError

