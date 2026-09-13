"""Create the sensor readings table.

Revision ID: 20260913_0001
Revises:
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sensor_readings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sensor_id", sa.String(length=80), nullable=False),
        sa.Column("metric", sa.String(length=80), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=24), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("anomaly_score", sa.Float(), nullable=False),
        sa.Column("is_anomaly", sa.Boolean(), nullable=False),
        sa.Column("detector_status", sa.String(length=24), nullable=False),
        sa.Column("baseline_center", sa.Float(), nullable=True),
        sa.Column("baseline_scale", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sensor_metric_recorded",
        "sensor_readings",
        ["sensor_id", "metric", "recorded_at"],
        unique=False,
    )
    op.create_index(
        "ix_sensor_readings_is_anomaly",
        "sensor_readings",
        ["is_anomaly"],
        unique=False,
    )
    op.create_index(
        "ix_sensor_readings_metric", "sensor_readings", ["metric"], unique=False
    )
    op.create_index(
        "ix_sensor_readings_recorded_at",
        "sensor_readings",
        ["recorded_at"],
        unique=False,
    )
    op.create_index(
        "ix_sensor_readings_sensor_id",
        "sensor_readings",
        ["sensor_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sensor_readings_sensor_id", table_name="sensor_readings")
    op.drop_index("ix_sensor_readings_recorded_at", table_name="sensor_readings")
    op.drop_index("ix_sensor_readings_metric", table_name="sensor_readings")
    op.drop_index("ix_sensor_readings_is_anomaly", table_name="sensor_readings")
    op.drop_index("ix_sensor_metric_recorded", table_name="sensor_readings")
    op.drop_table("sensor_readings")
