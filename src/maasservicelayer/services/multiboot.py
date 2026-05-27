# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from maasservicelayer.context import Context
from maasservicelayer.db.filters import QuerySpec
from maasservicelayer.db.repositories.multiboot import (
    MultiBootDeploymentRepository,
    MultiBootOSRepository,
    MultiBootPartitionRepository,
    MultiBootDeploymentClauseFactory,
    MultiBootOSClauseFactory,
    MultiBootPartitionClauseFactory,
)
from maasservicelayer.models.multiboot import (
    MultiBootDeployment,
    MultiBootOS,
    MultiBootPartition,
)
from maasservicelayer.builders.multiboot import (
        MultiBootDeploymentBuilder,
        MultiBootOSBuilder,
        MultiBootPartitionBuilder,
)
from maasservicelayer.services.base import BaseService, ServiceCache

class MultiBootOSService(
    BaseService[
        MultiBootOS,
        MultiBootOSRepository,
        MultiBootOSBuilder
    ]
):
    def __init__(
        self,
        context: Context,
        multiboot_os_repository: MultiBootOSRepository,
        cache: ServiceCache | None = None,
    ):
        super().__init__(context, multiboot_os_repository, cache)


class MultiBootPartitionService(
    BaseService[
        MultiBootPartition,
        MultiBootPartitionRepository,
        MultiBootPartitionBuilder,
    ]
):
    def __init__(
        self,
        context: Context,
        multiboot_partition_repository: MultiBootPartitionRepository,
        cache: ServiceCache | None = None,
    ):
        super().__init__(context, multiboot_partition_repository, cache)

class MultiBootDeploymentService(
    BaseService[
        MultiBootDeployment,
        MultiBootDeploymentRepository,
        MultiBootDeploymentBuilder
    ]
):
    def __init__(
        self,
        context: Context,
        multiboot_deployment_repository: MultiBootDeploymentRepository,
        multiboot_os_service: MultiBootOSService,
        multiboot_partition_service: MultiBootPartitionService,
        cache: ServiceCache | None = None,
    ):
        super().__init__(context, multiboot_deployment_repository, cache)
        self.os_repository = multiboot_os_service
        self.partition_repository = multiboot_partition_service

    async def store_layout(
        self,
        node_id: int,
        default_os_index: int,
        boot_timeout: int,
        oses_data: list,
    ) -> MultiBootDeployment:
        """Create a full multi-boot layout with OS entries and partitions."""
        from maasservicelayer.builders.multiboot import (
            MultiBootDeploymentBuilder,
            MultiBootOSBuilder,
            MultiBootPartitionBuilder,
        )

        # 1. Create the deployment row
        dep_builder = MultiBootDeploymentBuilder(
            node_id=node_id,
            default_os_index=default_os_index,
            boot_timeout=boot_timeout,
        )
        deployment = await self.repository.create(dep_builder)

        # 2. Create OS entries and partitions
        for os_data in oses_data:
            os_builder = MultiBootOSBuilder(
                deployment_id=deployment.id,
                osystem=os_data["osystem"],
                distro_series=os_data["distro_series"],
                hwe_kernel=os_data.get("hwe_kernel"),
                architecture=os_data.get("architecture"),
                priority=os_data.get("priority", 0),
                boot_disk_id=os_data.get("boot_disk_id"),
            )
            os_model = await self.os_service.create(os_builder)

            for part_data in os_data.get("partitions", []):
                part_builder = MultiBootPartitionBuilder(
                    os_entry_id=os_model.id,
                    mount_point=part_data["mount_point"],
                    size=part_data["size"],
                    fstype=part_data.get("fstype", "ext4"),
                )
                await self.partition_service.create(part_builder)

        return deployment

    async def get_layout(
        self, node_id: int
    ) -> tuple[MultiBootDeployment | None, list, list]:
        """Get a deployment with its full nested structure."""
        deployment = await self.repository.get_one(
            QuerySpec(
                where=MultiBootDeploymentClauseFactory.with_node_id(node_id)
            )
        )
        if not deployment:
            return None, [], []

        os_entries = await self.os_repository.get_many(
            QuerySpec(
                where=MultiBootOSClauseFactory.with_deployment_id(
                    deployment.id
                )
            )
        )

        all_oses_with_partitions = []
        for os_entry in os_entries:
            partitions = await self.partition_repository.get_many(
                QuerySpec(
                    where=MultiBootPartitionClauseFactory.with_os_entry_id(
                        os_entry.id
                    )
                )
            )
            all_oses_with_partitions.append((os_entry, partitions))

        return deployment, all_oses_with_partitions, []

    async def delete_layout(self, node_id: int) -> None:
        """Delete a deployment and cascade to children."""
        await self.repository.delete_one(
            QuerySpec(
                where=MultiBootDeploymentClauseFactory.with_node_id(node_id)
            )
        )


