"""maaservicelayer/models"
Service layer models for multi-boot deployment.

Maps to: src/maasservicelayer/models/multiboot.py (NEW)

Follows the MAAS 3.8 service layer pattern:
- @generate_builder() decorator for auto-generated builder classes
- MaasTimestampedBaseModel for created/updated timestamps
- Optional[str] = None for nullable fields
"""

__all__ = [
    "MultiBootDeployment",
    "MultiBootOS",
    "MultiBootPartition",
]

from typing import Optional

from maasservicelayer.models.base import (
    MaasTimestampedBaseModel,
    generate_builder,
)


@generate_builder()
class MultiBootDeployment(MaasTimestampedBaseModel):
    """Top-level multi-boot configuration for a single machine."""

    default_os_index: int
    boot_timeout: int
    node_id: int


@generate_builder()
class MultiBootOS(MaasTimestampedBaseModel):
    """An operating system entry within a multi-boot deployment."""

    osystem: str
    distro_series: str
    hwe_kernel: Optional[str] = None
    architecture: Optional[str] = None
    priority: int
    deployment_id: int
    boot_disk_id: Optional[int] = None


@generate_builder()
class MultiBootPartition(MaasTimestampedBaseModel):
    """A single partition definition within a multi-boot OS entry."""

    mount_point: str
    size: int
    fstype: str
    os_entry_id: int

