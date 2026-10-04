"""Store read-only content and submission notes alongside resources."""

import sqlalchemy as sa
from alembic import op

revision = "0002_resource_description"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("resources", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("resources", "description")
