"""Add per-series stream timeout overrides and receipt-time index."""

import sqlalchemy as sa
from alembic import op

revision = "20261021_0004"
down_revision = "20261016_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sensor_rules") as batch:
        batch.add_column(sa.Column("stale_after_seconds", sa.Integer(), nullable=True))
        batch.create_check_constraint(
            "ck_rules_stale_after", "stale_after_seconds BETWEEN 1 AND 604800"
        )
    op.create_index(
        "ix_sensor_metric_received", "sensor_readings", ["sensor_id", "metric", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_sensor_metric_received", table_name="sensor_readings")
    with op.batch_alter_table("sensor_rules") as batch:
        batch.drop_constraint("ck_rules_stale_after", type_="check")
        batch.drop_column("stale_after_seconds")
