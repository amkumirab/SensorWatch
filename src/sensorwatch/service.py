from __future__ import annotations

from collections import defaultdict

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from sensorwatch.config import Settings
from sensorwatch.detector import RollingMadDetector
from sensorwatch.models import SensorReading
from sensorwatch.schemas import (
    OverviewResponse,
    ReadingCreate,
    SensorSeriesSummary,
)


class ReadingService:
    def __init__(self, db: Session, settings: Settings):
        self.db = db
        self.detector = RollingMadDetector(
            window=settings.detector_window,
            min_samples=settings.detector_min_samples,
            threshold=settings.detector_threshold,
        )

    def add(self, payload: ReadingCreate) -> SensorReading:
        history_statement = (
            select(SensorReading.value)
            .where(
                SensorReading.sensor_id == payload.sensor_id,
                SensorReading.metric == payload.metric,
            )
            .order_by(desc(SensorReading.recorded_at), desc(SensorReading.id))
            .limit(self.detector.window)
        )
        history = list(reversed(self.db.scalars(history_statement).all()))
        detection = self.detector.detect(payload.value, history)

        row = SensorReading(
            sensor_id=payload.sensor_id,
            metric=payload.metric,
            value=payload.value,
            unit=payload.unit,
            recorded_at=payload.recorded_at,
            anomaly_score=detection.score,
            is_anomaly=detection.is_anomaly,
            detector_status=detection.status,
            baseline_center=detection.center,
            baseline_scale=detection.scale,
        )
        self.db.add(row)
        self.db.flush()
        return row


def list_readings(
    db: Session,
    *,
    sensor_id: str | None = None,
    metric: str | None = None,
    anomalies_only: bool = False,
    limit: int = 200,
) -> list[SensorReading]:
    statement = select(SensorReading)
    if sensor_id:
        statement = statement.where(SensorReading.sensor_id == sensor_id)
    if metric:
        statement = statement.where(SensorReading.metric == metric)
    if anomalies_only:
        statement = statement.where(SensorReading.is_anomaly.is_(True))
    statement = statement.order_by(
        desc(SensorReading.recorded_at), desc(SensorReading.id)
    ).limit(limit)
    return list(db.scalars(statement).all())


def overview(db: Session) -> OverviewResponse:
    total = db.scalar(select(func.count()).select_from(SensorReading)) or 0
    anomalies = (
        db.scalar(
            select(func.count())
            .select_from(SensorReading)
            .where(SensorReading.is_anomaly.is_(True))
        )
        or 0
    )
    active_series = (
        db.scalar(
            select(func.count()).select_from(
                select(SensorReading.sensor_id, SensorReading.metric)
                .distinct()
                .subquery()
            )
        )
        or 0
    )
    latest = db.scalar(select(func.max(SensorReading.recorded_at)))
    return OverviewResponse(
        total_readings=total,
        total_anomalies=anomalies,
        anomaly_rate=round(anomalies / total, 4) if total else 0.0,
        active_series=active_series,
        latest_recorded_at=latest,
    )


def series_summaries(db: Session) -> list[SensorSeriesSummary]:
    rows = list(
        db.scalars(
            select(SensorReading).order_by(
                SensorReading.sensor_id,
                SensorReading.metric,
                desc(SensorReading.recorded_at),
                desc(SensorReading.id),
            )
        ).all()
    )
    grouped: dict[tuple[str, str], list[SensorReading]] = defaultdict(list)
    for row in rows:
        grouped[(row.sensor_id, row.metric)].append(row)

    summaries = []
    for (sensor_id, metric), readings in grouped.items():
        latest = readings[0]
        summaries.append(
            SensorSeriesSummary(
                sensor_id=sensor_id,
                metric=metric,
                unit=latest.unit,
                total_readings=len(readings),
                anomaly_count=sum(item.is_anomaly for item in readings),
                last_value=latest.value,
                last_recorded_at=latest.recorded_at,
            )
        )
    return summaries
