"""Read-only health derived from the last committed connectivity check."""

from datetime import datetime

from sqlalchemy.orm import Session

from sensorwatch.config import get_settings
from sensorwatch.connectivity import utc_now
from sensorwatch.incidents import as_utc
from sensorwatch.models import MonitorHeartbeat
from sensorwatch.schemas import MonitorHealthResponse


def monitor_health(db: Session, *, now: datetime | None = None) -> MonitorHealthResponse:
    minimum_timeout = get_settings().monitor_health_timeout_seconds
    heartbeat = db.get(MonitorHeartbeat, 1)
    if heartbeat is None:
        return MonitorHealthResponse(
            status="not_started",
            last_success_at=None,
            age_seconds=None,
            timeout_seconds=minimum_timeout,
            interval_seconds=None,
            last_opened_incidents=None,
            last_recovered_incidents=None,
        )
    last_success = as_utc(heartbeat.last_success_at)
    age = max(
        0.0, (as_utc(now if now is not None else utc_now()) - last_success).total_seconds()
    )
    timeout = max(minimum_timeout, heartbeat.interval_seconds * 3)
    return MonitorHealthResponse(
        status="delayed" if age > timeout else "healthy",
        last_success_at=last_success,
        age_seconds=age,
        timeout_seconds=timeout,
        interval_seconds=heartbeat.interval_seconds,
        last_opened_incidents=heartbeat.opened_incidents,
        last_recovered_incidents=heartbeat.recovered_incidents,
    )
