# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from operator import eq
from typing import Type

from sqlalchemy import Table

from maasservicelayer.db.filters import Clause, ClauseFactory
from maasservicelayer.db.repositories.base import BaseRepository
from maasservicelayer.db.tables import (
    MultiBootDeploymentTable,
    MultiBootOSTable,
    MultiBootPartitionTable,
)
from maasservicelayer.models.multiboot import (
    MultiBootDeployment,
    MultiBootOS,
    MultiBootPartition,
)


class MultiBootDeploymentClauseFactory(ClauseFactory):
    @classmethod
    def with_id(cls, id: int) -> Clause:
        return Clause(condition=eq(MultiBootDeploymentTable.c.id, id))

    @classmethod
    def with_node_id(cls, node_id: int) -> Clause:
        return Clause(condition=eq(MultiBootDeploymentTable.c.node_id, node_id))


class MultiBootOSClauseFactory(ClauseFactory):
    @classmethod
    def with_id(cls, id: int) -> Clause:
        return Clause(condition=eq(MultiBootOSTable.c.id, id))

    @classmethod
    def with_deployment_id(cls, deployment_id: int) -> Clause:
        return Clause(
            condition=eq(MultiBootOSTable.c.deployment_id, deployment_id)
        )

    @classmethod
    def with_priority(cls, priority: int) -> Clause:
        return Clause(condition=eq(MultiBootOSTable.c.priority, priority))


class MultiBootPartitionClauseFactory(ClauseFactory):
    @classmethod
    def with_id(cls, id: int) -> Clause:
        return Clause(condition=eq(MultiBootPartitionTable.c.id, id))

    @classmethod
    def with_os_entry_id(cls, os_entry_id: int) -> Clause:
        return Clause(
            condition=eq(
                MultiBootPartitionTable.c.os_entry_id, os_entry_id
            )
        )

    @classmethod
    def with_mountpoint(cls, mountpoint: str) -> Clause:
        return Clause(
            condition=eq(MultiBootPartitionTable.c.mountpoint, mountpoint)
        )


class MultiBootDeploymentRepository(
    BaseRepository[MultiBootDeployment]
):
    def get_repository_table(self) -> Table:
        return MultiBootDeploymentTable

    def get_model_factory(self) -> Type[MultiBootDeployment]:
        return MultiBootDeployment

    def get_clause_factory(self) -> ClauseFactory:
        return MultiBootDeploymentClauseFactory


class MultiBootOSRepository(BaseRepository[MultiBootOS]):
    def get_repository_table(self) -> Table:
        return MultiBootOSTable

    def get_model_factory(self) -> Type[MultiBootOS]:
        return MultiBootOS

    def get_clause_factory(self) -> ClauseFactory:
        return MultiBootOSClauseFactory


class MultiBootPartitionRepository(
    BaseRepository[MultiBootPartition]
):
    def get_repository_table(self) -> Table:
        return MultiBootPartitionTable

    def get_model_factory(self) -> Type[MultiBootPartition]:
        return MultiBootPartition

    def get_clause_factory(self) -> ClauseFactory:
        return MultiBootPartitionClauseFactory

