from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sensorwatch.db import Base


class SensorReading(Base):
    __tablename__ = "sensor_readings"
    __table_args__ = (
        Index("ix_sensor_metric_recorded", "sensor_id", "metric", "recorded_at"),
        Index("ix_sensor_metric_received", "sensor_id", "metric", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sensor_id: Mapped[str] = mapped_column(String(80), index=True)
    metric: Mapped[str] = mapped_column(String(80), index=True)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(24), default="")
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    anomaly_score: Mapped[float] = mapped_column(Float, default=0.0)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    detector_status: Mapped[str] = mapped_column(String(24), default="warming-up")
    baseline_center: Mapped[float | None] = mapped_column(Float, nullable=True)
    baseline_scale: Mapped[float | None] = mapped_column(Float, nullable=True)
    applied_rule: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class SensorRule(Base):
    __tablename__ = "sensor_rules"
    __table_args__ = (
        CheckConstraint("lower_bound < upper_bound", name="ck_rules_bounds"),
        CheckConstraint("detector_threshold > 0", name="ck_rules_threshold"),
        CheckConstraint(
            "stale_after_seconds BETWEEN 1 AND 604800", name="ck_rules_stale_after"
        ),
    )

    sensor_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    metric: Mapped[str] = mapped_column(String(80), primary_key=True)
    lower_bound: Mapped[float | None] = mapped_column(Float, nullable=True)
    upper_bound: Mapped[float | None] = mapped_column(Float, nullable=True)
    detector_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    stale_after_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ConnectivityIncident(Base):
    __tablename__ = "connectivity_incidents"
    __table_args__ = (
        CheckConstraint("stale_after_seconds > 0", name="ck_incident_timeout"),
        CheckConstraint(
            "recovered_at IS NULL OR recovered_at >= started_at",
            name="ck_incident_recovery_time",
        ),
        CheckConstraint(
            "recovery_reason IS NULL OR recovery_reason IN "
            "('data_received', 'timeout_changed')",
            name="ck_incident_reason",
        ),
        Index("ix_incident_series_started", "sensor_id", "metric", "started_at"),
        Index("ix_incident_started", "started_at"),
        Index(
            "uq_incident_open_series",
            "sensor_id",
            "metric",
            unique=True,
            sqlite_where=text("recovered_at IS NULL"),
            postgresql_where=text("recovered_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sensor_id: Mapped[str] = mapped_column(String(80))
    metric: Mapped[str] = mapped_column(String(80))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stale_after_seconds: Mapped[int] = mapped_column(Integer)
    recovered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recovery_reason: Mapped[str | None] = mapped_column(String(24), nullable=True)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint("severity IN ('warning', 'critical')", name="ck_alerts_severity"),
        CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved')", name="ck_alerts_status"
        ),
        Index("ix_alerts_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reading_id: Mapped[int] = mapped_column(
        ForeignKey("sensor_readings.id", ondelete="CASCADE"), unique=True, index=True
    )
    severity: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    message: Mapped[str] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(80), nullable=True)

    reading: Mapped[SensorReading] = relationship(lazy="joined")
