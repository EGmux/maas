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
    "build_storage_config",
    "generate_multi_boot_installer",
]

import re
import yaml
from typing import Optional
import logging

from curtin.config import merge_config
from curtin.pack import pack

from maasserver.preseed import get_curtin_installer_url

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
from maasserver.enum import NODE_STATUS_CHOICES_DICT
from maasserver.node_status import NODE_TRANSITIONS
from maasserver.sqlalchemy import service_layer

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
    # 1. Try request.data (file upload or string)
    layout_file = request.data.get("layout")
    if layout_file is not None:
        try:
            if hasattr(layout_file, 'read'):
                raw = layout_file.read()
            else:
                raw = layout_file
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


def _parse_size(size_str: str | int) -> int:
    if isinstance(size_str, int):
        return size_str
    size_str = size_str.strip()
    units = {
        "B": 1,
        "K": 1024,
        "M": 1024**2,
        "G": 1024**3,
        "T": 1024**4,
        "P": 1024**5,
    }
    if size_str[-1].isalpha():
        unit = size_str[-1].upper()
        number = float(size_str[:-1].strip())
        return int(number * units.get(unit, 1))
    return int(float(size_str))


def build_storage_config(layout: dict) -> dict:
    """Build the master curtin storage config for all OSes.

    Produces a curtin ``storage`` block (``version: 1`` + ``config`` list)
    with actions for: shared disk, shared ESP (auto-injected), and per-OS
    partitions. Mount actions are created **only** for the first Linux OS
    (so ``block-meta --mode=custom`` mounts them in Phase 1).

    The user's ``/boot/efi`` partition entries are silently skipped —
    the shared ESP replaces them.

    Called **once** (not per-OS). The output is merged into ``config-000.cfg``.

    Parameters
    ----------
    layout : dict
        Canonical layout dict with ``boot`` and ``oses`` keys,
        as returned by ``load_layout()``.

    Returns
    -------
    dict
        A curtin storage config dict::

            {"version": 1, "config": [...]}
    """
    config = []
    oses = layout.get(_OSES_KEY, [])

    # 1. Shared disk
    config.append({
        "id": "sda",
        "type": "disk",
        "ptable": "gpt",
    })

    # 2. Shared ESP — always auto-injected as first partition.
    #    User-specified /boot/efi entries are skipped (handled below).
    config.append({
        "id": "esp",
        "type": "partition",
        "device": "sda",
        "size": "512M",
        "flag": "boot",
    })
    config.append({
        "id": "esp_fs",
        "type": "format",
        "volume": "esp",
        "fstype": "fat32",
    })
    config.append({
        "id": "esp_mnt",
        "type": "mount",
        "device": "esp_fs",
        "path": "/boot/efi",
    })

    # 3. Per-OS partitions
    part_num = 2  # sda2 onward (sda1 = ESP)
    first_linux = True

    for i, entry in enumerate(oses):
        prefix = f"os{i}"
        is_windows = entry.get(_OSYSTEM_KEY, "") == "windows"
        partitions = entry.get(_PARTITIONS_KEY, {})

        for mount_point, part_spec in partitions.items():
            # Skip /boot/efi — shared ESP handles it
            if mount_point == "/boot/efi":
                continue

            part_id = f"{prefix}_p{part_num}"

            # Partition action
            config.append({
                "id": part_id,
                "type": "partition",
                "device": "sda",
                "size": part_spec["size"],
            })

            # Format action
            fs_id = f"{part_id}_fs"
            config.append({
                "id": fs_id,
                "type": "format",
                "volume": part_id,
                "fstype": part_spec[_FSTYPE_KEY],
            })

            # Mount action — only for the first Linux OS
            if not is_windows and first_linux:
                config.append({
                    "id": f"{part_id}_mnt",
                    "type": "mount",
                    "device": fs_id,
                    "path": mount_point,
                })

            part_num += 1

        # Mark first Linux as done after processing its partitions
        if not is_windows and first_linux:
            first_linux = False

    return {"version": 1, "config": config}


import textwrap


def _generate_orchestrator(
    oses: list[dict],
    urls: list[str],
    default_index: int,
    timeout: int,
    system_id: str,
    metadata_url: str,
) -> str:
    """Generate the multi-boot orchestrator bash script.

    Returns a ``multi-boot.sh`` script that runs in the MAAS ephemeral
    initrd environment. Called by ``generate_multi_boot_installer()``
    which bakes the result into a self-extracting archive via ``pack()``.

    Parameters
    ----------
    oses : list[dict]
        The ``oses`` list from the layout dict.
    urls : list[str]
        Resolved image URLs (prefix stripped), one per OS entry.
    default_index : int
        Index of the default OS in the GRUB menu.
    timeout : int
        GRUB menu timeout in seconds.
    system_id : str
        Machine system_id (baked in for netboot_off URL).
    metadata_url : str
        MAAS metadata service URL (baked in for netboot_off).

    Returns
    -------
    str
        The complete bash orchestrator script.
    """
    os_count = len(oses)
    os_types = " ".join('"%s"' % e["osystem"] for e in oses)
    url_list = " ".join('"%s"' % u for u in urls)

    return textwrap.dedent('''\
    #!/bin/bash
    set -euo pipefail

    # ── Baked-in metadata ──
    OS_COUNT=%s
    OSYSTEM=(%s)
    IMAGE_URLS=(%s)
    DEFAULT_OS=%s
    TIMEOUT=%s
    SYSTEM_ID="%s"
    MAAS_METADATA_URL="%s"

    # ── Phase 1: Partition once ──
    echo "[multiboot] Phase 1: Partition all disks"
    TARGET_MOUNT_POINT=/target/os0 \\
    curtin block-meta --mode=custom --config configs/config-000.cfg

    # ── Phase 2: Install each OS ──
    for ((i=0; i<OS_COUNT; i++)); do
        echo "[multiboot] Installing OS ${i} (${OSYSTEM[$i]})"

        if [[ "${OSYSTEM[$i]}" == "windows" ]]; then
            # ── Windows: losetup + dd + zcat ──
            PART_NUM=$((i + 2))
            START=$(cat "/sys/block/sda/sda${PART_NUM}/start")
            SIZE=$(cat "/sys/block/sda/sda${PART_NUM}/size")
            losetup -o $((START * 512)) --sizelimit $((SIZE * 512)) \\
                --show /dev/sda /dev/loop0
            wget "${IMAGE_URLS[$i]}" --progress=dot:mega -O - \\
                | zcat | dd bs=4M of=/dev/loop0
            losetup -d /dev/loop0
            partprobe /dev/sda
            udevadm settle
        else
            # ── Linux: extract + curthooks ──
            if [[ $i -ne 0 ]]; then
                PART_NUM=$((i + 2))
                mkdir -p "/target/os${i}"
                mount "/dev/sda${PART_NUM}" "/target/os${i}"
            fi
            curtin extract --config "configs/config-${i}.cfg" \\
                --target "/target/os${i}" "${IMAGE_URLS[$i]}"
            curtin curthooks --config "configs/config-${i}.cfg" \\
                --target "/target/os${i}"
        fi
    done

    # ── Phase 3: GRUB handled by curthooks' setup_boot() ──

    # ── Phase 4: Signal completion ──
    echo "[multiboot] Phase 4: netboot_off"
    wget --post-data="" -q -O /dev/null \\
        "http://${MAAS_METADATA_URL}/MAAS/metadata/latest/${SYSTEM_ID}/?op=netboot_off"

    echo "[multiboot] Done. Rebooting."
    ''' % (os_count, os_types, url_list, default_index, timeout, system_id, metadata_url))


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
    deployment, os_entries, _ = service_layer.services.multiboot_deployments.get_layout(
        machine.id
    )
    if deployment is None:
        return None
    
    oses_list = []
    for os_entry, partitions in os_entries:
        partitions_dict = {}
        for part in partitions:
            partitions_dict[part.mount_point] = {
                "size": part.size,
                "fstype": part.fstype,
            }
        os_dict = {
            "osystem": os_entry.osystem,
            "distro_series": os_entry.distro_series,
            "hwe_kernel": os_entry.hwe_kernel,
            "architecture": os_entry.architecture,
            "priority": os_entry.priority,
            "boot_disk_id": os_entry.boot_disk_id,
            "partitions": partitions_dict,
        }
        oses_list.append(os_dict)
    
    return {
        "boot": {
            "default": deployment.default_os_index,
            "timeout": deployment.boot_timeout,
        },
        "oses": oses_list,
    }


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
    boot = layout_data.get("boot", {})
    oses = layout_data.get("oses", [])
    
    oses_data = []
    for i, os_entry in enumerate(oses):
        partitions_data = []
        for mount_point, part_config in os_entry.get("partitions", {}).items():
            partitions_data.append({
                "mount_point": mount_point,
                "size": _parse_size(part_config["size"]),
                "fstype": part_config.get("fstype", "ext4"),
            })
        oses_data.append({
            "osystem": os_entry["osystem"],
            "distro_series": os_entry["distro_series"],
            "hwe_kernel": os_entry.get("hwe_kernel"),
            "architecture": os_entry.get("architecture"),
            "priority": os_entry.get("priority", i),
            "boot_disk_id": os_entry.get("boot_disk_id"),
            "partitions": partitions_data,
        })
    
    service_layer.services.multiboot_deployments.store_layout(
        node_id=node.id,
        default_os_index=boot.get("default", 0),
        boot_timeout=boot.get("timeout", 5),
        oses_data=oses_data,
    )


def generate_multi_boot_installer(
    layout: dict, machine, os_configs: list[str]
) -> str:
    """Generate the multi-boot wrapper script.

    Produces a self-extracting ``#!/bin/sh`` archive (via ``curtin.pack.pack()``)
    containing the bundled curtin Python library, N per-OS curtin YAML configs,
    and an orchestrator script (``multi-boot.sh``) that installs each OS in
    sequence.

    Parameters
    ----------
    layout : dict
        Canonical layout dict with ``boot`` and ``oses``.
    machine : Node
        The machine (used to resolve image URLs, disk info).
    os_configs : list[str]
        Per-OS curtin YAML configs produced by ``compose_os_config()``.
        One per entry in ``layout["oses"]``, in the same order.
        Storage section already stripped by ``compose_os_config()``.

    Returns
    -------
    str
        A self-extracting shell archive (``#!/bin/sh``). Stored in
        NodeMetadata and served verbatim by the metadata service at
        PXE time (same contract as ``pack_install()`` output).
    """
    # 1. Resolve image URLs per OS entry
    urls = []
    for entry in layout["oses"]:
        old_osystem = machine.osystem
        old_series = machine.distro_series
        try:
            machine.osystem = entry["osystem"]
            machine.distro_series = entry["distro_series"]
            raw_url = get_curtin_installer_url(machine)
        finally:
            machine.osystem = old_osystem
            machine.distro_series = old_series
        # Strip known URL prefixes: "dd-gz:http://..." → "http://..."
        # "tgz:http://..." → "http://..."
        # "cp:///path" stays as-is (handled by orchestrator)
        clean_url = re.sub(r'^[a-z][a-z0-9-]*:', '', raw_url)
        urls.append(clean_url)

    # 2. Build master storage config
    master_storage = build_storage_config(layout)

    # 3. Merge storage into config-000 only.
    #    Per-OS configs (001, 002, ...) have no storage section.
    config_yamls = []
    for i, yaml_str in enumerate(os_configs):
        cfg = yaml.safe_load(yaml_str)
        if i == 0:
            cfg = merge_config(cfg, {"storage": master_storage})
        config_yamls.append(yaml.safe_dump(cfg))

    # 4. Generate orchestrator script
    orch = _generate_orchestrator(
        oses=layout["oses"],
        urls=urls,
        default_index=layout["boot"].get("default", 0),
        timeout=layout["boot"].get("timeout", 5),
        system_id=machine.system_id,
        metadata_url=str(machine.boot_cluster_ip),
    )

    # 5. Bundle via pack() — same mechanism as pack_install()
    config_files = [
        (f"configs/config-{i:03d}.cfg", yaml_str)
        for i, yaml_str in enumerate(config_yamls)
    ]
    config_files.append(("multi-boot.sh", orch))

    return pack(
        command=["/bin/bash", "multi-boot.sh"],
        add_files=config_files,
    )


def delete_layout(machine: Node) -> None:
    """Delete all multi-boot data for a machine.
    
    Parameters
    ----------
    machine : Node
    """
    service_layer.services.multiboot_deployments.delete_layout(machine.id)
    NodeMetadata.objects.filter(
        node=machine, key__startswith="multi_boot_"
    ).delete()

