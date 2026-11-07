"""Store the last successful connectivity check atomically with incidents."""

import sqlalchemy as sa
from alembic import op

revision = "20261107_0006"
down_revision = "20261027_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monitor_heartbeats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("opened_incidents", sa.Integer(), nullable=False),
        sa.Column("recovered_incidents", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_monitor_singleton"),
        sa.CheckConstraint("interval_seconds BETWEEN 1 AND 3600", name="ck_monitor_interval"),
        sa.CheckConstraint(
            "opened_incidents >= 0 AND recovered_incidents >= 0", name="ck_monitor_counts"
        ),
    )


def downgrade() -> None:
    op.drop_table("monitor_heartbeats")
