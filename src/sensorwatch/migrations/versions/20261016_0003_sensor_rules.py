"""Add per-series rules and immutable reading rule snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "20261016_0003"
down_revision = "20260924_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sensor_rules",
        sa.Column("sensor_id", sa.String(80), primary_key=True),
        sa.Column("metric", sa.String(80), primary_key=True),
        sa.Column("lower_bound", sa.Float(), nullable=True),
        sa.Column("upper_bound", sa.Float(), nullable=True),
        sa.Column("detector_threshold", sa.Float(), nullable=True),
        sa.CheckConstraint("lower_bound < upper_bound", name="ck_rules_bounds"),
        sa.CheckConstraint("detector_threshold > 0", name="ck_rules_threshold"),
    )
    op.add_column("sensor_readings", sa.Column("applied_rule", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("sensor_readings", "applied_rule")
    op.drop_table("sensor_rules")
