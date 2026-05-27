# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from maasservicelayer.db.mappers.default import DefaultDomainDataMapper
from maasservicelayer.db.tables import (
    MultiBootDeploymentTable,
    MultiBootOSTable,
    MultiBootPartitionTable,
)


class MultiBootDeploymentMapper(DefaultDomainDataMapper):
    def __init__(self):
        super().__init__(MultiBootDeploymentTable)


class MultiBootOSMapper(DefaultDomainDataMapper):
    def __init__(self):
        super().__init__(MultiBootOSTable)


class MultiBootPartitionMapper(DefaultDomainDataMapper):
    def __init__(self):
        super().__init__(MultiBootPartitionTable)

