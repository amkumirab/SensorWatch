"""Stream freshness measured from receipt timestamps, independent of device clocks."""

from datetime import datetime, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from sensorwatch.config import get_settings
from sensorwatch.models import SensorReading, SensorRule
from sensorwatch.schemas import SeriesConnectivity


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def stream_health(
    db: Session, *, now: datetime | None = None
) -> dict[tuple[str, str], SeriesConnectivity]:
    now = now if now is not None else utc_now()
    default_timeout = get_settings().stale_after_seconds
    statement = (
        select(
            SensorReading.sensor_id,
            SensorReading.metric,
            func.max(SensorReading.created_at),
            SensorRule.stale_after_seconds,
        )
        .outerjoin(
            SensorRule,
            and_(
                SensorRule.sensor_id == SensorReading.sensor_id,
                SensorRule.metric == SensorReading.metric,
            ),
        )
        .group_by(SensorReading.sensor_id, SensorReading.metric, SensorRule.stale_after_seconds)
    )
    health = {}
    for sensor_id, metric, received, override in db.execute(statement):
        # SQLite does not preserve timezone information for DateTime columns.
        if received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
        timeout = override if override is not None else default_timeout
        age = max(0.0, (now - received).total_seconds())
        health[(sensor_id, metric)] = SeriesConnectivity(
            last_received_at=received,
            connectivity_status="stale" if age > timeout else "online",
            stale_after_seconds=timeout,
        )
    return health
