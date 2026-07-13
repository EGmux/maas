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
import textwrap
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
            raise MAASAPIBadRequest("Invalid YAML: %s" % exc)

    # 2. Try request.POST (raw string)
    raw = request.POST.get("layout")
    if raw is not None:
        try:
            return yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise MAASAPIBadRequest("Invalid YAML: %s" % exc)

    # 3. Try request.FILES (multipart file upload from CLI)
    layout_file = request.FILES.get("layout")
    if layout_file is not None:
        try:
            raw = layout_file.read()
            return yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise MAASAPIBadRequest("Invalid YAML: %s" % exc)

    raise MAASAPIBadRequest("No layout file provided.")


def validate_layout(layout_data: dict) -> None:
    """Validate layout structure."""
    if not isinstance(layout_data, dict):
        raise MAASAPIValidationError("Layout must be a dict.")
    if _BOOT_KEY not in layout_data:
        raise MAASAPIValidationError("Layout must contain a '%s' key." % _BOOT_KEY)
    if _OSES_KEY not in layout_data:
        raise MAASAPIValidationError("Layout must contain an '%s' key." % _OSES_KEY)
    boot = layout_data[_BOOT_KEY]
    oses = layout_data[_OSES_KEY]
    if not isinstance(oses, list):
        raise MAASAPIValidationError("'%s' must be a list, got %s." % (_OSES_KEY, type(oses).__name__))
    if len(oses) < _MIN_OS_COUNT:
        raise MAASAPIValidationError("'%s' must contain at least %d entries, got %d." % (_OSES_KEY, _MIN_OS_COUNT, len(oses)))
    if not isinstance(boot, dict):
        raise MAASAPIValidationError("'%s' must be a dict, got %s." % (_BOOT_KEY, type(boot).__name__))
    default_index = boot.get(_DEFAULT_KEY, 0)
    if not isinstance(default_index, int) or default_index < 0:
        raise MAASAPIValidationError("'%s.%s' must be a non-negative integer." % (_BOOT_KEY, _DEFAULT_KEY))
    if default_index >= len(oses):
        raise MAASAPIValidationError("'%s.%s' (%d) is out of range for %d OS entries." % (_BOOT_KEY, _DEFAULT_KEY, default_index, len(oses)))
    timeout = boot.get(_TIMEOUT_KEY, 5)
    if not isinstance(timeout, int) or timeout < 0:
        raise MAASAPIValidationError("'%s.%s' must be a non-negative integer." % (_BOOT_KEY, _TIMEOUT_KEY))
    for i, os_entry in enumerate(oses):
        validate_os_entry(os_entry, i)


def validate_os_entry(os_entry: dict, index: int) -> None:
    """Validate a single OS entry within the layout."""
    prefix = "'oses[%d]'" % index
    if not isinstance(os_entry, dict):
        raise MAASAPIValidationError("%s must be a dict, got %s." % (prefix, type(os_entry).__name__))
    if _OSYSTEM_KEY not in os_entry:
        raise MAASAPIValidationError("%s missing required key '%s'." % (prefix, _OSYSTEM_KEY))
    if _DISTRO_SERIES_KEY not in os_entry:
        raise MAASAPIValidationError("%s missing required key '%s'." % (prefix, _DISTRO_SERIES_KEY))
    osystem = os_entry[_OSYSTEM_KEY]
    if _PARTITIONS_KEY not in os_entry:
        raise MAASAPIValidationError("%s missing required key '%s'." % (prefix, _PARTITIONS_KEY))
    partitions = os_entry[_PARTITIONS_KEY]
    if not isinstance(partitions, dict):
        raise MAASAPIValidationError("%s '%s' must be a dict, got %s." % (prefix, _PARTITIONS_KEY, type(partitions).__name__))
    if "/" not in partitions:
        raise MAASAPIValidationError("%s '%s' must contain a root partition ('/')." % (prefix, _PARTITIONS_KEY))
    for mount_point, part_config in partitions.items():
        validate_partition(part_config, mount_point, prefix, osystem)


def validate_partition(part_config, mount_point: str, os_prefix: str, osystem: str) -> None:
    """Validate a single partition entry."""
    prefix = "%s '%s'['%s']" % (os_prefix, _PARTITIONS_KEY, mount_point)
    if not isinstance(part_config, dict):
        raise MAASAPIValidationError("%s must be a dict, got %s." % (prefix, type(part_config).__name__))
    if _SIZE_KEY not in part_config:
        raise MAASAPIValidationError("%s missing required key '%s'." % (prefix, _SIZE_KEY))
    if _FSTYPE_KEY not in part_config:
        raise MAASAPIValidationError("%s missing required key '%s'." % (prefix, _FSTYPE_KEY))
    fstype = part_config[_FSTYPE_KEY]
    if fstype not in _ALLOWED_FSTYPES:
        raise MAASAPIValidationError("%s '%s' unsupported fstype '%s'. Allowed: %s." % (prefix, _FSTYPE_KEY, fstype, _ALLOWED_FSTYPES))
    if fstype == "ntfs" and osystem != "windows":
        raise MAASAPIValidationError("%s fstype 'ntfs' is only supported for osystem 'windows', got '%s'." % (prefix, osystem))


def compose_os_config(request, machine, os_entry: dict, index: int) -> str:
    """Generate a single-OS curtin config for one entry in the layout."""
    osystem = os_entry[_OSYSTEM_KEY]
    series = os_entry[_DISTRO_SERIES_KEY]
    old_osystem = machine.osystem
    old_series = machine.distro_series
    try:
        machine.osystem = osystem
        machine.distro_series = series
        merged = get_curtin_merged_config(request, machine)
    finally:
        machine.osystem = old_osystem
        machine.distro_series = old_series
    merged.pop("storage", None)
    return yaml.safe_dump(merged)


def _parse_size(size_str: str | int) -> int:
    if isinstance(size_str, int):
        return size_str
    size_str = size_str.strip()
    units = {"B": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4, "P": 1024**5}
    if size_str[-1].isalpha():
        unit = size_str[-1].upper()
        number = float(size_str[:-1].strip())
        return int(number * units.get(unit, 1))
    return int(float(size_str))


def build_storage_config(layout: dict, machine=None) -> dict:
    """Build the master curtin storage config for all OSes."""
    config = []
    oses = layout.get(_OSES_KEY, [])

    # 1. Shared disk — use real device from commissioned hardware data
    disk_name = "sda"
    if machine:
        if machine.boot_disk:
            disk_name = machine.boot_disk.name or "sda"
        else:
            pbd = PhysicalBlockDevice.objects.filter(node_config__node=machine).first()
            if pbd:
                disk_name = pbd.name or (pbd.id_path.rstrip("/").split("/")[-1] if pbd.id_path else "sda")
    maaslog.info("build_storage_config: resolved disk_name=%s (boot_disk=%s)", disk_name,
                 machine.boot_disk.name if machine and machine.boot_disk else "None")

    config.append({"id": disk_name, "type": "disk", "ptable": "gpt", "path": "/dev/%s" % disk_name, "name": disk_name})

    # 2. Shared ESP
    config.append({"id": "esp", "type": "partition", "device": disk_name, "size": "512M", "flag": "boot"})
    config.append({"id": "esp_fs", "type": "format", "volume": "esp", "fstype": "fat32"})
    config.append({"id": "esp_mnt", "type": "mount", "device": "esp_fs", "path": "/boot/efi"})

    # 3. Per-OS partitions
    part_num = 2
    first_linux = True
    for i, entry in enumerate(oses):
        prefix = f"os{i}"
        is_windows = entry.get(_OSYSTEM_KEY, "") == "windows"
        partitions = entry.get(_PARTITIONS_KEY, {})
        for mount_point, part_spec in partitions.items():
            if mount_point == "/boot/efi":
                continue
            part_id = f"{prefix}_p{part_num}"
            config.append({"id": part_id, "type": "partition", "device": disk_name, "size": part_spec["size"]})
            fs_id = f"{part_id}_fs"
            config.append({"id": fs_id, "type": "format", "volume": part_id, "fstype": part_spec[_FSTYPE_KEY]})
            if not is_windows and first_linux:
                config.append({"id": f"{part_id}_mnt", "type": "mount", "device": fs_id, "path": mount_point})
            part_num += 1
        if not is_windows and first_linux:
            first_linux = False

    return {"version": 1, "config": config}


def _generate_orchestrator(
    oses: list[dict],
    urls: list[str],
    default_index: int,
    timeout: int,
    system_id: str,
    metadata_url: str,
) -> str:
    """Generate the multi-boot orchestrator bash script."""
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

    # ── Set curtin environment variables (standard paths) ──
    export WORKING_DIR=/tmp/curtin
    export CONFIG=configs/config-000.cfg
    export OUTPUT_FSTAB=/tmp/curtin/fstab
    export OUTPUT_INTERFACES=/tmp/curtin/interfaces
    export OUTPUT_NETWORK_STATE=/tmp/curtin/network_state
    export OUTPUT_NETWORK_CONFIG=/tmp/curtin/network_config
    export TARGET_MOUNT_POINT=/target/os0
    mkdir -p "$WORKING_DIR"

    # ── Detect the actual primary block disk device identifier ──
    if [ -b /dev/vda ]; then
        DISK_DEV="vda"
    elif [ -b /dev/nvme0n1 ]; then
        DISK_DEV="nvme0n1"
    elif [ -b /dev/sda ]; then
        DISK_DEV="sda"
    else
        echo "[multiboot] ERROR: No valid target block device located!" >&2
        ls -la /dev/
        exit 1
    fi
    echo "[multiboot] Target block drive assigned to: /dev/${DISK_DEV}"

    # ── Phase 1: Partition once ──
    echo "[multiboot] Phase 1: Partition all disks"
    curtin -c configs/config-000.cfg block-meta custom

    # ── Phase 2: Install each OS ──
    for ((i=0; i<OS_COUNT; i++)); do
        echo "[multiboot] Installing OS ${i} (${OSYSTEM[$i]})"

        # ESP stays mounted — T-12 GRUB patch skips GRUB on secondary OSes

        if [[ "${OSYSTEM[$i]}" == "windows" ]]; then
            # ── Windows: losetup + dd + zcat ──
            PART_NUM=$((i + 2))
            if [[ "$DISK_DEV" =~ "nvme" ]]; then
                PART_DEV="${DISK_DEV}p${PART_NUM}"
            else
                PART_DEV="${DISK_DEV}${PART_NUM}"
            fi
            START=$(cat "/sys/block/${DISK_DEV}/${PART_DEV}/start")
            SIZE=$(cat "/sys/block/${DISK_DEV}/${PART_DEV}/size")
            losetup -o $((START * 512)) --sizelimit $((SIZE * 512)) \\
                --show "/dev/${DISK_DEV}" /dev/loop0
            wget "${IMAGE_URLS[$i]}" --progress=dot:mega -O - \\
                | zcat | dd bs=4M of=/dev/loop0
            losetup -d /dev/loop0
            partprobe "/dev/${DISK_DEV}"
            udevadm settle
        else
            # ── Linux: extract + curthooks ──
            if [[ $i -ne 0 ]]; then
                PART_NUM=$((i + 2))
                if [[ "$DISK_DEV" =~ "nvme" ]]; then
                    PART_DEV="${DISK_DEV}p${PART_NUM}"
                else
                    PART_DEV="${DISK_DEV}${PART_NUM}"
                fi
                mkdir -p "/target/os${i}"
                mount "/dev/${PART_DEV}" "/target/os${i}"
            fi
            CFG_INDEX=$(printf "%%03d" $i)
            export CONFIG="configs/config-${CFG_INDEX}.cfg"
            curtin -c "configs/config-${CFG_INDEX}.cfg" extract \\
                --target "/target/os${i}" "${IMAGE_URLS[$i]}"
            # Generate network config file before curthooks
            curtin -c "configs/config-${CFG_INDEX}.cfg" net-meta custom

            curtin -c "configs/config-${CFG_INDEX}.cfg" curthooks \\
                --target "/target/os${i}"
        fi

        # Clean curtin state for next OS iteration
        rm -rf /tmp/curtin/*
    done
    # -- Phase 3: Fix grub
    cat << 'EOF' > /tmp/execute_phase3.sh
    #!/bin/bash
    set -euo pipefail

    echo "[multiboot] Phase 3: Commencing filesystem validation and structural scan..."

    TARGET_DISK="/dev/vda"
    EFI_PART="/dev/vda1"
    OS1_PART="/dev/vda3"
    OS0_MOUNT="/target/os0"
    OS1_MOUNT="/target/os1"

    HOST_EFI_UUID=$(blkid -s UUID -o value "$EFI_PART" || echo "")
    HOST_OS1_UUID=$(blkid -s UUID -o value "$OS1_PART" || echo "")

    # Ensure target directories are ready
    mkdir -p "$OS0_MOUNT"

    # ========================================================================
    # 1. DEEP FILE GEOMETRY DIAGNOSTIC DUMP
    # ========================================================================
    echo "========================================================================"
    echo "[multiboot-diag] DEBUG: SCANNING SHARED EFI PARTITION STRUCTURE"
    echo "========================================================================"
    if [ -d "${OS0_MOUNT}/boot/efi" ]; then
        find "${OS0_MOUNT}/boot/efi" -type f -name "*.efi" -o -name "*.cfg" || true
    else
        echo "EFI mount point directory not initialized yet."
    fi

    echo "------------------------------------------------------------------------"
    echo "[multiboot-diag] DEBUG: SCANNING SECONDARY OS KERNELS AND INITRD IMAGES"
    echo "------------------------------------------------------------------------"
    if [ -d "${OS1_MOUNT}/boot" ]; then
        ls -la "${OS1_MOUNT}/boot" || true
    else
        echo "Warning: /target/os1/boot directory cannot be reached!"
    fi
    echo "========================================================================"

    # ========================================================================
    # 2. IDENTIFY REAL SYSTEM LABELS
    # ========================================================================
    HOST_OS_NAME=""
    if [ -f "${OS1_MOUNT}/etc/os-release" ]; then
        HOST_OS_NAME=$(grep '^PRETTY_NAME=' "${OS1_MOUNT}/etc/os-release" | head -n 1 | cut -d'=' -f2 | tr -d '"' | tr -d "'")
    fi
    if [ -z "$HOST_OS_NAME" ]; then
        HOST_OS_NAME="Ubuntu 24.04 LTS (Fallback)"
    fi

    # ========================================================================
    # 3. CONSTRUCT GRUB DRIVER PAYLOAD
    # ========================================================================
    mkdir -p /tmp/grub_payload
    cat << 'PAYLOAD_EOF' > /tmp/grub_payload/40_custom
#!/bin/sh
exec tail -n +3 $0
# Dedicated Multi-Boot Orchestrator Advanced Boot Directives

PAYLOAD_EOF

    # DYNAMICALLY CAPTURE ABSOLUTE FILENAMES FOR KERNEL & INITRD
    KERNEL_FILE=$(ls -1 ${OS1_MOUNT}/boot/vmlinuz-* 2>/dev/null | sort -V | tail -n 1 | sed "s|^${OS1_MOUNT}||" || echo "")
    INITRD_FILE=$(ls -1 ${OS1_MOUNT}/boot/initrd.img-* 2>/dev/null | sort -V | tail -n 1 | sed "s|^${OS1_MOUNT}||" || echo "")

    # Verification fallback checks if names were returned clean
    if [ ! -z "$KERNEL_FILE" ] && [ ! -z "$INITRD_FILE" ]; then
        echo "[multiboot] Valid core engine located. Injecting Direct Kernel Exec execution profile."
        cat << L_EOF >> /tmp/grub_payload/40_custom
menuentry "TARGET_OS_NAME_PLACEHOLDER (Direct Kernel Boot)" --class os {
    insmod ext2
    insmod part_gpt
    search --no-floppy --fs-uuid --set=root TARGET_OS1_UUID_PLACEHOLDER
    linux TARGET_KERNEL_PLACEHOLDER root=UUID=TARGET_OS1_UUID_PLACEHOLDER ro quiet splash
    initrd TARGET_INITRD_PLACEHOLDER
}
L_EOF
    else
        echo "[multiboot] WARNING: Direct images missing. Compiling EFI Chainloader fallback profile."
        cat << C_EOF >> /tmp/grub_payload/40_custom
menuentry "TARGET_OS_NAME_PLACEHOLDER (EFI Chainloader Fallback)" --class os {
    insmod fat
    insmod part_gpt
    search --no-floppy --fs-uuid --set=root TARGET_EFI_UUID_PLACEHOLDER
    chainloader (\${root})/EFI/ubuntu/grubx64.efi
}
C_EOF
    fi

    # Token String Replacements
    sed -i "s|TARGET_OS_NAME_PLACEHOLDER|$HOST_OS_NAME|g" /tmp/grub_payload/40_custom
    sed -i "s|TARGET_OS1_UUID_PLACEHOLDER|$HOST_OS1_UUID|g" /tmp/grub_payload/40_custom
    sed -i "s|TARGET_EFI_UUID_PLACEHOLDER|$HOST_EFI_UUID|g" /tmp/grub_payload/40_custom
    sed -i "s|TARGET_KERNEL_PLACEHOLDER|$KERNEL_FILE|g" /tmp/grub_payload/40_custom
    sed -i "s|TARGET_INITRD_PLACEHOLDER|$INITRD_FILE|g" /tmp/grub_payload/40_custom

    # ========================================================================
    # 4. INJECT AND COMPILE CONFIGURATIONS
    # ========================================================================
    if ! grep -q " /target/os0 " /proc/mounts; then
        mount "${TARGET_DISK}2" "/target/os0"
    fi

    mount --bind /dev "/target/os0/dev" 2>/dev/null || true
    mount --bind /proc "/target/os0/proc" 2>/dev/null || true
    mount --bind /sys "/target/os0/sys" 2>/dev/null || true
    mount --bind /sys/firmware/efi/efivars "/target/os0/sys/firmware/efi/efivars" 2>/dev/null || true

    cp /tmp/grub_payload/40_custom /target/os0/etc/grub.d/40_custom
    chmod +x /target/os0/etc/grub.d/40_custom

    export EFI_PART TARGET_DISK
    chroot "/target/os0" bash -s << 'CHROOT_EOF'
        set -euo pipefail
        
        mkdir -p /boot/efi
        if ! grep -q " /boot/efi " /proc/mounts; then
            mount "$EFI_PART" /boot/efi
        fi

        echo "[multiboot-chroot] Normalizing central default GRUB parameters..."
        if [ -f "/etc/default/grub" ]; then
            sed -i 's/GRUB_DISABLE_OS_PROBER=false/GRUB_DISABLE_OS_PROBER=true/g' /etc/default/grub
            if ! grep -q "GRUB_DISABLE_OS_PROBER" /etc/default/grub; then
                echo "GRUB_DISABLE_OS_PROBER=true" >> /etc/default/grub
            fi
            sed -i 's/GRUB_TIMEOUT_STYLE=hidden/GRUB_TIMEOUT_STYLE=menu/g' /etc/default/grub
            if ! grep -q "GRUB_TIMEOUT_STYLE" /etc/default/grub; then
                echo "GRUB_TIMEOUT_STYLE=menu" >> /etc/default/grub
            fi
            sed -i 's/GRUB_TIMEOUT=[0-9]*/GRUB_TIMEOUT=10/g' /etc/default/grub
            if ! grep -q "GRUB_TIMEOUT=" /etc/default/grub; then
                echo "GRUB_TIMEOUT=10" >> /etc/default/grub
            fi
        fi

        echo "[multiboot-chroot] Compiling boot configurations..."
        if type -p update-grub >/dev/null 2>&1; then
            grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=ubuntu --recheck "$TARGET_DISK"
            update-grub 2>&1
            cp /boot/grub/grub.cfg /boot/efi/EFI/ubuntu/grub.cfg 2>/dev/null || true
        fi

        mkdir -p /boot/efi/EFI/BOOT
        if [ -f /boot/efi/EFI/ubuntu/grubx64.efi ]; then
            cp /boot/efi/EFI/ubuntu/grubx64.efi /boot/efi/EFI/BOOT/BOOTX64.EFI 2>/dev/null || true
            cp /boot/grub/grub.cfg /boot/efi/EFI/BOOT/grub.cfg 2>/dev/null || true
        fi

        umount /boot/efi || true
CHROOT_EOF

    echo "[multiboot] Cleaning up shared workspace mounts..."
    umount -l "/target/os0/sys/firmware/efi/efivars" 2>/dev/null || true
    umount -l "/target/os0/sys" 2>/dev/null || true
    umount -l "/target/os0/dev" 2>/dev/null || true
    umount -l "/target/os0/proc" 2>/dev/null || true
    umount -l "/target/os0" 2>/dev/null || true
EOF

    # ── Run the generated Phase 3 script ──
    chmod +x /tmp/execute_phase3.sh
    /tmp/execute_phase3.sh

    # ── Phase 4: Signal completion (Main Script Context) ──
    cat << 'EOF' > /tmp/execute_phase4.sh
    #!/bin/bash
    set -euo pipefail

    echo "[multiboot] Phase 4: Disabling PXE network boot hooks inside MAAS..."
    
    # Ensure network metadata signals block and flush to MAAS explicitly
    wget --timeout=5 --tries=3 --post-data="" -q -O /dev/null \
        "http://${MAAS_METADATA_URL}/MAAS/metadata/latest/${SYSTEM_ID}/?op=netboot_off" || echo "MAAS notify failed"

    echo "[multiboot] Infrastructure clear. Holding execution for cluster state registration..."
    sleep 10

    echo "[multiboot] Executing structural block sync..."
    sync

    echo "[multiboot] Initiating clean system hardware restart..."
    reboot
EOF
    wget --post-data="" -q -O /dev/null \
        "http://${MAAS_METADATA_URL}/MAAS/metadata/latest/${SYSTEM_ID}/?op=netboot_off" || echo "MAAS notify skipped"

    echo "[multiboot] Done. Forcing clean hardware reboot in 60s..."
    
    # CRITICAL: Disable strict mode so the background fork doesn't trip up the parent exit codes!
    set +euo pipefail
    
    # The true fork/subshell trick: runs in the background and releases cloud-init immediately
    (sleep 60; shutdown -r now) >/dev/null 2>&1 &

    exit 0
    ''' % (os_count, os_types, url_list, default_index, timeout, system_id, metadata_url))


def load_layout(machine) -> Optional[dict]:
    """Read layout from models into the canonical dict format."""
    deployment, os_entries, _ = service_layer.services.multiboot_deployments.get_layout(machine.id)
    if deployment is None:
        return None
    oses_list = []
    for os_entry, partitions in os_entries:
        partitions_dict = {}
        for part in partitions:
            partitions_dict[part.mount_point] = {"size": part.size, "fstype": part.fstype}
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
    return {"boot": {"default": deployment.default_os_index, "timeout": deployment.boot_timeout}, "oses": oses_list}


@transaction.atomic
def store_layout(node: Node, layout_data: dict) -> None:
    """Write layout dict into MultiBootDeployment + related models."""
    boot = layout_data.get("boot", {})
    oses = layout_data.get("oses", [])
    oses_data = []
    for i, os_entry in enumerate(oses):
        partitions_data = []
        for mount_point, part_config in os_entry.get("partitions", {}).items():
            partitions_data.append({"mount_point": mount_point, "size": _parse_size(part_config["size"]), "fstype": part_config.get("fstype", "ext4")})
        oses_data.append({
            "osystem": os_entry["osystem"], "distro_series": os_entry["distro_series"],
            "hwe_kernel": os_entry.get("hwe_kernel"), "architecture": os_entry.get("architecture"),
            "priority": os_entry.get("priority", i), "boot_disk_id": os_entry.get("boot_disk_id"),
            "partitions": partitions_data,
        })
    service_layer.services.multiboot_deployments.store_layout(
        node_id=node.id, default_os_index=boot.get("default", 0), boot_timeout=boot.get("timeout", 5), oses_data=oses_data,
    )


def generate_multi_boot_installer(layout: dict, machine, os_configs: list[str]) -> str:
    """Generate the multi-boot wrapper script.

    Produces a self-extracting ``#!/bin/sh`` archive (via ``curtin.pack.pack()``)
    containing the bundled curtin Python library, N per-OS curtin YAML configs,
    and an orchestrator script (``multi-boot.sh``) that installs each OS in sequence.
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
        maaslog.info("URL scrub: raw_url=%s", raw_url)
        if re.match(r'^[a-z][a-z0-9-]*:http', raw_url):
            clean_url = re.sub(r'^[a-z][a-z0-9-]*:', '', raw_url)
        else:
            clean_url = raw_url
        if not clean_url:
            maaslog.error("Empty image URL for %s/%s (hwe=%s)", entry.get("osystem"), entry.get("distro_series"), entry.get("hwe_kernel"))
            clean_url = "cp:///media/root-ro"
        urls.append(clean_url)

    # ── Validate total partition size against disk capacity ──
    ESP_BYTES = 512 * 1024 * 1024
    total_requested = ESP_BYTES
    for entry in layout["oses"]:
        for mount_point, part_spec in entry.get("partitions", {}).items():
            total_requested += _parse_size(part_spec["size"])
    disk_size = 0
    disk_name = "unknown"
    if machine.boot_disk:
        disk_size = machine.boot_disk.size or 0
        disk_name = machine.boot_disk.name or "unknown"
    else:
        pbd = PhysicalBlockDevice.objects.filter(node_config__node=machine).first()
        if pbd:
            disk_size = pbd.size or 0
            disk_name = pbd.name or "unknown"
    if disk_size > 0 and total_requested > disk_size:
        requested_gb = total_requested / (1024**3)
        disk_gb = disk_size / (1024**3)
        raise MAASAPIValidationError(
            "Requested multi-boot partition layout allocation (%.1f GB) exceeds the target disk capacity (%.1f GB) available on device '%s'."
            % (requested_gb, disk_gb, disk_name)
        )
    maaslog.info("Disk space validation: %.1f GB requested on %s (disk size: %.1f GB, %s)",
                 total_requested / (1024**3), disk_name, disk_size / (1024**3) if disk_size else 0,
                 "skipped (no disk info)" if disk_size == 0 else "passed")

    # 2. Build master storage config
    master_storage = build_storage_config(layout, machine)

    # 3. Extract network config from first OS's preseed (retains network from
    #    get_curtin_merged_config after storage is stripped)
    net_config = None
    first_cfg = yaml.safe_load(os_configs[0])
    if isinstance(first_cfg, dict):
        # The network config key is "network_commands" (not "network")
        net_config = first_cfg.get("network_commands", None)
        maaslog.info(
            "Network config: %s (keys available: %s)",
            "found" if net_config else "NOT FOUND",
            list(first_cfg.keys()),
        )

    # 4. Merge storage into config-000 and inject network into all OS configs
    config_yamls = []
    for i, yaml_str in enumerate(os_configs):
        cfg = yaml.safe_load(yaml_str)
        if cfg is None or not isinstance(cfg, dict):
            cfg = {}
        if i == 0:
            merge_config(cfg, {"storage": master_storage})  # mutates cfg in-place
        else:
            cfg["grub_device"] = False
            cfg.pop("datasource", None)
            cfg.pop("cloud_config", None)
            cfg.pop("reporting", None)
            cfg.pop("rsyslog", None)
        # Inject network_commands into every OS so curtin's net-meta works
        if net_config:
            cfg["network_commands"] = net_config
        config_yamls.append(yaml.safe_dump(cfg))

    # Log config contents for debugging
    for i, yaml_str in enumerate(config_yamls):
        maaslog.info("config-%03d.cfg: %d bytes — %s", i, len(yaml_str), yaml_str[:200].replace("\n", "\\n"))

    # Scrub any remaining hardcoded "sda" from config YAMLs
    real_disk = master_storage["config"][0].get("id", "sda")
    if real_disk != "sda":
        for i, yaml_str in enumerate(config_yamls):
            config_yamls[i] = yaml_str.replace("sda", real_disk)
            maaslog.info("config-%03d.cfg scrubbed: sda → %s", i, real_disk)

    # 5. Generate orchestrator script
    orch = _generate_orchestrator(
        oses=layout["oses"], urls=urls,
        default_index=layout["boot"].get("default", 0),
        timeout=layout["boot"].get("timeout", 5),
        system_id=machine.system_id,
        metadata_url=str(machine.boot_cluster_ip),
    )

    # 6. Bundle via pack()
    config_files = [(f"configs/config-{i:03d}.cfg", yaml_str) for i, yaml_str in enumerate(config_yamls)]
    config_files.append(("multi-boot.sh", orch))
    return pack(command=["/bin/bash", "multi-boot.sh"], add_files=config_files)


def delete_layout(machine: Node) -> None:
    """Delete all multi-boot data for a machine."""
    service_layer.services.multiboot_deployments.delete_layout(machine.id)
    NodeMetadata.objects.filter(node=machine, key__startswith="multi_boot_").delete()




