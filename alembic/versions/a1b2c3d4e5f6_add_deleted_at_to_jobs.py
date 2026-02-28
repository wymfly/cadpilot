"""add deleted_at to jobs

Revision ID: a1b2c3d4e5f6
Revises: 9d813f751dc5
Create Date: 2026-02-28 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '9d813f751dc5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add deleted_at column to jobs table for soft-delete support."""
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    """Remove deleted_at column from jobs table."""
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_column('deleted_at')
