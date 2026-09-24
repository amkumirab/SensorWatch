from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sensorwatch.db import Base


class SensorReading(Base):
    __tablename__ = "sensor_readings"
    __table_args__ = (
        Index("ix_sensor_metric_recorded", "sensor_id", "metric", "recorded_at"),
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('warning', 'critical')", name="ck_alerts_severity"
        ),
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
