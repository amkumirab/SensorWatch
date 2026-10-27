"""Persist connectivity incidents and enforce one open incident per series."""

import sqlalchemy as sa
from alembic import op

revision = "20261027_0005"
down_revision = "20261021_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connectivity_incidents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sensor_id", sa.String(80), nullable=False),
        sa.Column("metric", sa.String(80), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stale_after_seconds", sa.Integer(), nullable=False),
        sa.Column("recovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovery_reason", sa.String(24), nullable=True),
        sa.CheckConstraint("stale_after_seconds > 0", name="ck_incident_timeout"),
        sa.CheckConstraint(
            "recovered_at IS NULL OR recovered_at >= started_at",
            name="ck_incident_recovery_time",
        ),
        sa.CheckConstraint(
            "recovery_reason IS NULL OR recovery_reason IN "
            "('data_received', 'timeout_changed')",
            name="ck_incident_reason",
        ),
    )
    op.create_index(
        "ix_incident_series_started",
        "connectivity_incidents",
        ["sensor_id", "metric", "started_at"],
    )
    op.create_index("ix_incident_started", "connectivity_incidents", ["started_at"])
    op.create_index(
        "uq_incident_open_series",
        "connectivity_incidents",
        ["sensor_id", "metric"],
        unique=True,
        sqlite_where=sa.text("recovered_at IS NULL"),
        postgresql_where=sa.text("recovered_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("connectivity_incidents")
