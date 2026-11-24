from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256

from sqlalchemy import desc, func, select, text
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, joinedload

from sensorwatch.config import Settings
from sensorwatch.connectivity import stream_health
from sensorwatch.detector import RollingMadDetector
from sensorwatch.models import Alert, SensorReading, SensorRule
from sensorwatch.schemas import (
    OverviewResponse,
    ReadingCreate,
    SensorSeriesSummary,
)


class IdempotencyConflict(ValueError):
    pass


def _request_digest(payload: ReadingCreate) -> str:
    content = {
        "value": 0.0 if payload.value == 0 else payload.value,
        "unit": payload.unit,
        # A generated server timestamp must not make an otherwise identical retry conflict.
        "recorded_at": (
            payload.recorded_at.isoformat(timespec="microseconds")
            if "recorded_at" in payload.model_fields_set
            else None
        ),
    }
    return sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class ReadingService:
    def __init__(self, db: Session, settings: Settings):
        self.db = db
        self.created_count = 0
        self.replayed_count = 0
        self.detector = RollingMadDetector(
            window=settings.detector_window,
            min_samples=settings.detector_min_samples,
            threshold=settings.detector_threshold,
        )

    def add(self, payload: ReadingCreate) -> SensorReading:
        row = None
        if payload.event_id is not None:
            self._lock_events([payload])
            digest = _request_digest(payload)
            insert = (
                sqlite_insert
                if self.db.get_bind().dialect.name == "sqlite"
                else postgres_insert
            )
            claim = (
                insert(SensorReading)
                .values(
                    sensor_id=payload.sensor_id,
                    metric=payload.metric,
                    event_id=payload.event_id,
                    request_digest=digest,
                    value=payload.value,
                    unit=payload.unit,
                    recorded_at=payload.recorded_at,
                )
                .on_conflict_do_nothing(index_elements=["sensor_id", "metric", "event_id"])
                .returning(SensorReading.id)
            )
            claimed_id = self.db.scalar(claim)
            if claimed_id is None:
                original = self.db.scalars(
                    select(SensorReading).where(
                        SensorReading.sensor_id == payload.sensor_id,
                        SensorReading.metric == payload.metric,
                        SensorReading.event_id == payload.event_id,
                    )
                ).one()
                if original.request_digest != digest:
                    raise IdempotencyConflict(
                        "event_id already exists with different reading data"
                    )
                self.replayed_count += 1
                return original
            row = self.db.get(SensorReading, claimed_id)
        row = self._add_new(payload, row)
        self.created_count += 1
        return row

    def add_batch(self, payloads: list[ReadingCreate]) -> list[SensorReading]:
        self._lock_events(payloads)
        return [self.add(payload) for payload in payloads]

    def _lock_events(self, payloads: list[ReadingCreate]) -> None:
        if self.db.get_bind().dialect.name != "postgresql":
            return
        lock_ids = {
            int.from_bytes(
                sha256(
                    json.dumps(
                        [
                            "sensorwatch:reading-event",
                            payload.sensor_id,
                            payload.metric,
                            payload.event_id,
                        ],
                        separators=(",", ":"),
                    ).encode()
                ).digest()[:8],
                "big",
                signed=True,
            )
            for payload in payloads
            if payload.event_id is not None
        }
        # Acquire the entire batch's locks in one order, even if clients reverse the events.
        for lock_id in sorted(lock_ids):
            self.db.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id}
            )

    def _add_new(self, payload: ReadingCreate, row: SensorReading | None) -> SensorReading:
        rule = self.db.get(SensorRule, (payload.sensor_id, payload.metric))
        detector = self.detector
        if rule is not None and rule.detector_threshold is not None:
            detector = RollingMadDetector(
                window=detector.window,
                min_samples=detector.min_samples,
                threshold=rule.detector_threshold,
            )
        history_statement = (
            select(SensorReading.value)
            .where(
                SensorReading.sensor_id == payload.sensor_id,
                SensorReading.metric == payload.metric,
            )
            .order_by(desc(SensorReading.recorded_at), desc(SensorReading.id))
            .limit(self.detector.window)
        )
        if row is not None:
            history_statement = history_statement.where(SensorReading.id != row.id)
        history = list(reversed(self.db.scalars(history_statement).all()))
        detection = detector.detect(payload.value, history)
        outside_bounds = rule is not None and (
            (rule.lower_bound is not None and payload.value < rule.lower_bound)
            or (rule.upper_bound is not None and payload.value > rule.upper_bound)
        )

        if row is None:
            row = SensorReading(
                sensor_id=payload.sensor_id,
                metric=payload.metric,
                value=payload.value,
                unit=payload.unit,
                recorded_at=payload.recorded_at,
            )
        row.anomaly_score = detection.score
        row.is_anomaly = detection.is_anomaly or outside_bounds
        row.detector_status = "anomaly" if outside_bounds else detection.status
        row.baseline_center = detection.center
        row.baseline_scale = detection.scale
        row.applied_rule = (
            {
                "lower_bound": rule.lower_bound,
                "upper_bound": rule.upper_bound,
                "detector_threshold": detector.threshold,
            }
            if rule is not None
            else None
        )
        self.db.add(row)
        self.db.flush()
        if row.is_anomaly:
            severity = (
                "critical"
                if outside_bounds or detection.score >= detector.threshold * 2
                else "warning"
            )
            self.db.add(
                Alert(
                    reading_id=row.id,
                    severity=severity,
                    status="open",
                    message=(
                        f"{severity.title()} {payload.metric} "
                        f"{'limit breach' if outside_bounds else 'anomaly detected'} "
                        f"on {payload.sensor_id}"
                    ),
                )
            )
            self.db.flush()
        return row


class AlertStateError(ValueError):
    pass


def _get_alert_for_update(db: Session, alert_id: int) -> Alert | None:
    return db.scalar(
        select(Alert)
        .options(joinedload(Alert.reading))
        .where(Alert.id == alert_id)
        .with_for_update()
    )


def list_alerts(
    db: Session,
    *,
    status: str | None = None,
    severity: str | None = None,
    active_only: bool = False,
    limit: int = 100,
) -> list[Alert]:
    statement = select(Alert).options(joinedload(Alert.reading))
    if status:
        statement = statement.where(Alert.status == status)
    if severity:
        statement = statement.where(Alert.severity == severity)
    if active_only:
        statement = statement.where(Alert.status != "resolved")
    statement = statement.order_by(desc(Alert.created_at), desc(Alert.id)).limit(limit)
    return list(db.scalars(statement).all())


def acknowledge_alert(db: Session, alert_id: int, operator: str) -> Alert | None:
    alert = _get_alert_for_update(db, alert_id)
    if alert is None:
        return None
    if alert.status == "acknowledged":
        return alert
    if alert.status != "open":
        raise AlertStateError(f"Cannot acknowledge an alert in {alert.status} state")
    alert.status = "acknowledged"
    alert.acknowledged_at = datetime.now(timezone.utc)
    alert.acknowledged_by = operator
    db.flush()
    return alert


def resolve_alert(db: Session, alert_id: int, operator: str) -> Alert | None:
    alert = _get_alert_for_update(db, alert_id)
    if alert is None:
        return None
    if alert.status == "resolved":
        return alert
    if alert.status != "acknowledged":
        raise AlertStateError("An alert must be acknowledged before it can be resolved")
    alert.status = "resolved"
    alert.resolved_at = datetime.now(timezone.utc)
    alert.resolved_by = operator
    db.flush()
    return alert


def list_readings(
    db: Session,
    *,
    sensor_id: str | None = None,
    metric: str | None = None,
    anomalies_only: bool = False,
    recorded_from: datetime | None = None,
    recorded_to: datetime | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[SensorReading]:
    statement = select(SensorReading)
    if sensor_id:
        statement = statement.where(SensorReading.sensor_id == sensor_id)
    if metric:
        statement = statement.where(SensorReading.metric == metric)
    if anomalies_only:
        statement = statement.where(SensorReading.is_anomaly.is_(True))
    if recorded_from is not None:
        statement = statement.where(SensorReading.recorded_at >= recorded_from)
    if recorded_to is not None:
        statement = statement.where(SensorReading.recorded_at <= recorded_to)
    statement = (
        statement.order_by(desc(SensorReading.recorded_at), desc(SensorReading.id))
        .offset(offset)
        .limit(limit)
    )
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
                select(SensorReading.sensor_id, SensorReading.metric).distinct().subquery()
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
        stale_series=sum(
            item.connectivity_status == "stale" for item in stream_health(db).values()
        ),
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

    health = stream_health(db)
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
                **health[(sensor_id, metric)].model_dump(),
            )
        )
    return summaries
