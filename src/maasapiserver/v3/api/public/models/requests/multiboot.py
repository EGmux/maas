# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from typing import List, Optional

from pydantic import BaseModel

from maasservicelayer.builders.multiboot import (
    MultiBootDeploymentBuilder,
    MultiBootOSBuilder,
    MultiBootPartitionBuilder,
)


class PartitionRequest(BaseModel):
    """A single partition within a multi-boot OS entry."""

    mount_point: str
    size: int
    fstype: str = "ext4"


class OsEntryRequest(BaseModel):
    """An operating system entry within a multi-boot deployment."""

    osystem: str
    distro_series: str
    hwe_kernel: Optional[str] = None
    architecture: Optional[str] = None
    priority: int = 0
    boot_disk_id: Optional[int] = None
    partitions: List[PartitionRequest] = []


class SetLayoutRequest(BaseModel):
    """Request body for setting a multi-boot layout on a machine."""

    default_os_index: int = 0
    boot_timeout: int = 5
    oses: List[OsEntryRequest] = []

