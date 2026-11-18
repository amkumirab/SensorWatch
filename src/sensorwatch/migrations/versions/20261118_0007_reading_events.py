"""Deduplicate sensor events within each sensor/metric series."""

import sqlalchemy as sa
from alembic import op

revision = "20261118_0007"
down_revision = "20261107_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sensor_readings", sa.Column("event_id", sa.String(128), nullable=True))
    op.add_column("sensor_readings", sa.Column("request_digest", sa.String(64), nullable=True))
    op.create_index(
        "uq_sensor_metric_event",
        "sensor_readings",
        ["sensor_id", "metric", "event_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_sensor_metric_event", table_name="sensor_readings")
    with op.batch_alter_table("sensor_readings") as batch:
        batch.drop_column("request_digest")
        batch.drop_column("event_id")
