"""Durable connectivity history with serialized monitor transactions."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from sensorwatch.connectivity import stream_health, utc_now
from sensorwatch.models import ConnectivityIncident, SensorReading
from sensorwatch.schemas import ConnectivityIncidentResponse


def as_utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def monitor_once(sessions: sessionmaker, *, now: datetime | None = None) -> dict[str, int]:
    with sessions() as db:
        # All monitor processes take the same lock. SQLite also excludes ingestion writes
        # during the short check; PostgreSQL uses a transaction-scoped advisory lock.
        if db.get_bind().dialect.name == "sqlite":
            db.execute(text("BEGIN IMMEDIATE"))
        else:
            db.execute(text("SELECT pg_advisory_xact_lock(73573001)"))
        checked_at = as_utc(now if now is not None else utc_now())
        counts = _check(db, checked_at)
        db.commit()
        return counts


def _check(db: Session, now: datetime) -> dict[str, int]:
    health = stream_health(db, now=now)
    open_rows = db.scalars(
        select(ConnectivityIncident).where(ConnectivityIncident.recovered_at.is_(None))
    ).all()
    active = {(row.sensor_id, row.metric): row for row in open_rows}
    last_recoveries = {
        (sensor, metric): as_utc(recovered)
        for sensor, metric, recovered in db.execute(
            select(
                ConnectivityIncident.sensor_id,
                ConnectivityIncident.metric,
                func.max(ConnectivityIncident.recovered_at),
            )
            .where(ConnectivityIncident.recovered_at.is_not(None))
            .group_by(ConnectivityIncident.sensor_id, ConnectivityIncident.metric)
        )
    }
    counts = {"opened": 0, "recovered": 0}
    for key, current in health.items():
        incident = active.get(key)
        if incident is not None:
            received_data = current.last_received_at > as_utc(incident.last_received_at)
            if received_data or current.connectivity_status == "online":
                if received_data:
                    first = db.scalar(
                        select(func.min(SensorReading.created_at)).where(
                            SensorReading.sensor_id == key[0],
                            SensorReading.metric == key[1],
                            SensorReading.created_at > incident.last_received_at,
                        )
                    )
                    recovered_at = as_utc(first)
                else:
                    recovered_at = now
                incident.recovered_at = max(as_utc(incident.started_at), recovered_at)
                incident.recovery_reason = (
                    "data_received" if received_data else "timeout_changed"
                )
                last_recoveries[key] = incident.recovered_at
                counts["recovered"] += 1
                del active[key]
        if current.connectivity_status == "stale" and key not in active:
            started = current.last_received_at + timedelta(seconds=current.stale_after_seconds)
            if key in last_recoveries:
                started = max(started, last_recoveries[key])
            db.add(
                ConnectivityIncident(
                    sensor_id=key[0],
                    metric=key[1],
                    started_at=started,
                    detected_at=now,
                    last_received_at=current.last_received_at,
                    stale_after_seconds=current.stale_after_seconds,
                )
            )
            counts["opened"] += 1
    db.flush()
    return counts


def list_incidents(
    db: Session,
    *,
    sensor_id: str | None = None,
    metric: str | None = None,
    status: str | None = None,
    started_from: datetime | None = None,
    started_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ConnectivityIncidentResponse]:
    statement = select(ConnectivityIncident)
    if sensor_id is not None:
        statement = statement.where(ConnectivityIncident.sensor_id == sensor_id)
    if metric is not None:
        statement = statement.where(ConnectivityIncident.metric == metric)
    if status == "open":
        statement = statement.where(ConnectivityIncident.recovered_at.is_(None))
    elif status == "recovered":
        statement = statement.where(ConnectivityIncident.recovered_at.is_not(None))
    if started_from is not None:
        statement = statement.where(ConnectivityIncident.started_at >= as_utc(started_from))
    if started_to is not None:
        statement = statement.where(ConnectivityIncident.started_at <= as_utc(started_to))
    rows = db.scalars(
        statement.order_by(
            ConnectivityIncident.started_at.desc(), ConnectivityIncident.id.desc()
        )
        .offset(offset)
        .limit(limit)
    ).all()
    now = utc_now()
    return [
        ConnectivityIncidentResponse(
            id=row.id,
            sensor_id=row.sensor_id,
            metric=row.metric,
            started_at=as_utc(row.started_at),
            detected_at=as_utc(row.detected_at),
            last_received_at=as_utc(row.last_received_at),
            stale_after_seconds=row.stale_after_seconds,
            recovered_at=as_utc(row.recovered_at) if row.recovered_at else None,
            recovery_reason=row.recovery_reason,
            status="recovered" if row.recovered_at else "open",
            duration_seconds=max(
                0.0, (as_utc(row.recovered_at or now) - as_utc(row.started_at)).total_seconds()
            ),
        )
        for row in rows
    ]
