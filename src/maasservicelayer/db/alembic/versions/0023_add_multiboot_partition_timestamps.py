"""add_multiboot_partition timestamps

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-05 20:59:21.024151+00:00

"""
from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0023'
down_revision: str | None = '0022'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Update your cascade foreign keys cleanly
    op.drop_constraint('maasserver_multibootos_deployment_id_fkey', 'maasserver_multibootos', type_='foreignkey')
    op.create_foreign_key(None, 'maasserver_multibootos', 'maasserver_multibootdeployment', ['deployment_id'], ['id'], ondelete='CASCADE', initially='DEFERRED', deferrable=True)
    
    op.drop_constraint('maasserver_multibootpartition_os_entry_id_fkey', 'maasserver_multibootpartition', type_='foreignkey')
    op.create_foreign_key(None, 'maasserver_multibootpartition', 'maasserver_multibootos', ['os_entry_id'], ['id'], ondelete='CASCADE', initially='DEFERRED', deferrable=True)

    # 2. Safely add your new feature columns (Handles both cases if columns exist or need creation)
    # Using raw SQL executes smoothly regardless of weird ORM state detection
    op.execute("ALTER TABLE maasserver_multibootpartition ADD COLUMN IF NOT EXISTS created TIMESTAMP WITH TIME ZONE DEFAULT NOW()")
    op.execute("ALTER TABLE maasserver_multibootpartition ADD COLUMN IF NOT EXISTS updated TIMESTAMP WITH TIME ZONE DEFAULT NOW()")
    
    # 3. Ensure they are locked down to NOT NULL as intended by the ORM model
    op.alter_column('maasserver_multibootpartition', 'created', nullable=False)
    op.alter_column('maasserver_multibootpartition', 'updated', nullable=False)


def downgrade() -> None:
    op.alter_column('maasserver_multibootpartition', 'updated', nullable=True)
    op.alter_column('maasserver_multibootpartition', 'created', nullable=True)
    op.drop_column('maasserver_multibootpartition', 'updated')
    op.drop_column('maasserver_multibootpartition', 'created')
    
    op.drop_constraint(None, 'maasserver_multibootpartition', type_='foreignkey')
    op.create_foreign_key('maasserver_multibootpartition_os_entry_id_fkey', 'maasserver_multibootpartition', 'maasserver_multibootos', ['os_entry_id'], ['id'], initially='DEFERRED', deferrable=True)
    
    op.drop_constraint(None, 'maasserver_multibootos', type_='foreignkey')
    op.create_foreign_key('maasserver_multibootos_deployment_id_fkey', 'maasserver_multibootos', 'maasserver_multibootdeployment', ['deployment_id'], ['id'], initially='DEFERRED', deferrable=True)
