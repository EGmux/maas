# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from typing import List, Optional, Self

from maasapiserver.v3.api.public.models.responses.base import (
    BaseHal,
    BaseHref,
    HalResponse,
    PaginatedResponse,
)
from maasservicelayer.models.multiboot import MultiBootDeployment


class PartitionResponse(HalResponse[BaseHal]):
    kind = "Partition"
    id: int
    mount_point: str
    size: int
    fstype: str

    @classmethod
    def from_model(cls, partition, self_base_hyperlink: str) -> Self:
        return cls(
            id=partition.id,
            mount_point=partition.mount_point,
            size=partition.size,
            fstype=partition.fstype,
            hal_links=BaseHal(
                self=BaseHref(
                    href=f"{self_base_hyperlink.rstrip('/')}/{partition.id}"
                )
            ),
        )


class OsEntryResponse(HalResponse[BaseHal]):
    kind = "OsEntry"
    id: int
    osystem: str
    distro_series: str
    hwe_kernel: Optional[str] = None
    architecture: Optional[str] = None
    priority: int
    boot_disk_id: Optional[int] = None
    partitions: List[PartitionResponse] = []

    @classmethod
    def from_model(cls, os_entry, partitions: List, self_base_hyperlink: str) -> Self:
        return cls(
            id=os_entry.id,
            osystem=os_entry.osystem,
            distro_series=os_entry.distro_series,
            hwe_kernel=os_entry.hwe_kernel,
            architecture=os_entry.architecture,
            priority=os_entry.priority,
            boot_disk_id=os_entry.boot_disk_id,
            partitions=[
                PartitionResponse.from_model(p, self_base_hyperlink)
                for p in partitions
            ],
            hal_links=BaseHal(
                self=BaseHref(
                    href=f"{self_base_hyperlink.rstrip('/')}/{os_entry.id}"
                )
            ),
        )


class MultiBootDeploymentResponse(HalResponse[BaseHal]):
    kind = "MultiBootDeployment"
    id: int
    node_id: int
    default_os_index: int
    boot_timeout: int
    oses: List[OsEntryResponse] = []

    @classmethod
    def from_model(
        cls,
        deployment: MultiBootDeployment,
        os_entries: List,
        self_base_hyperlink: str,
    ) -> Self:
        return cls(
            id=deployment.id,
            node_id=deployment.node_id,
            default_os_index=deployment.default_os_index,
            boot_timeout=deployment.boot_timeout,
            oses=[
                OsEntryResponse.from_model(
                    os_entry, partitions, self_base_hyperlink
                )
                for os_entry, partitions in os_entries
            ],
            hal_links=BaseHal(
                self=BaseHref(
                    href=f"{self_base_hyperlink.rstrip('/')}/{deployment.id}"
                )
            ),
        )


class MultiBootDeploymentListResponse(
    PaginatedResponse[MultiBootDeploymentResponse]
):
    kind = "MultiBootDeploymentList"

