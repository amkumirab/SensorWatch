import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from sensorwatch.db import Base
from sensorwatch.incidents import monitor_once
from sensorwatch.models import ConnectivityIncident, SensorReading, SensorRule

NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


@pytest.fixture
def sessions(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'incidents.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def receive(sessions, when, sensor="pump", metric="pressure"):
    with sessions.begin() as db:
        db.add(
            SensorReading(
                sensor_id=sensor,
                metric=metric,
                value=2,
                unit="bar",
                recorded_at=NOW + timedelta(days=100),
                created_at=when,
            )
        )


def test_monitor_boundary_idempotency_and_first_receipt_recovery(sessions):
    receive(sessions, NOW - timedelta(seconds=300))
    assert monitor_once(sessions, now=NOW) == {"opened": 0, "recovered": 0}
    assert monitor_once(sessions, now=NOW + timedelta(seconds=1))["opened"] == 1
    assert monitor_once(sessions, now=NOW + timedelta(seconds=2))["opened"] == 0
    receive(sessions, NOW + timedelta(seconds=3))
    receive(sessions, NOW + timedelta(seconds=7))
    assert monitor_once(sessions, now=NOW + timedelta(seconds=10))["recovered"] == 1
    with sessions() as db:
        rows = db.scalars(select(ConnectivityIncident)).all()
        assert len(rows) == 1
        assert rows[0].started_at.replace(tzinfo=timezone.utc) == NOW
        assert rows[0].recovered_at.replace(tzinfo=timezone.utc) == NOW + timedelta(seconds=3)
        assert rows[0].recovery_reason == "data_received"


def test_new_outage_after_recovery_between_checks(sessions):
    receive(sessions, NOW - timedelta(seconds=400))
    monitor_once(sessions, now=NOW)
    receive(sessions, NOW + timedelta(seconds=1))
    counts = monitor_once(sessions, now=NOW + timedelta(seconds=302))
    assert counts == {"opened": 1, "recovered": 1}
    with sessions() as db:
        assert len(db.scalars(select(ConnectivityIncident)).all()) == 2
    assert monitor_once(sessions, now=NOW + timedelta(seconds=303))["opened"] == 0


def test_concurrent_monitors_do_not_duplicate_open_incidents(sessions):
    receive(sessions, NOW - timedelta(seconds=301))
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: monitor_once(sessions, now=NOW), range(2)))
    assert sum(item["opened"] for item in results) == 1
    with sessions() as db:
        assert len(db.scalars(select(ConnectivityIncident)).all()) == 1


def test_timeout_changes_close_with_explicit_reason(sessions):
    receive(sessions, NOW - timedelta(seconds=301))
    monitor_once(sessions, now=NOW)
    with sessions.begin() as db:
        db.add(SensorRule(sensor_id="pump", metric="pressure", stale_after_seconds=600))
    assert monitor_once(sessions, now=NOW + timedelta(seconds=1))["recovered"] == 1
    with sessions() as db:
        row = db.scalar(select(ConnectivityIncident))
        assert row.recovery_reason == "timeout_changed"


def test_incident_api_filters_and_duration(client):
    from sensorwatch.api import app
    from sensorwatch.db import get_db

    generator = app.dependency_overrides[get_db]()
    db = next(generator)
    try:
        db.add_all(
            [
                ConnectivityIncident(
                    sensor_id="pump",
                    metric="pressure",
                    started_at=NOW,
                    detected_at=NOW,
                    last_received_at=NOW - timedelta(seconds=300),
                    stale_after_seconds=300,
                    recovered_at=NOW + timedelta(seconds=10),
                    recovery_reason="data_received",
                ),
                ConnectivityIncident(
                    sensor_id="boiler",
                    metric="temperature",
                    started_at=NOW,
                    detected_at=NOW,
                    last_received_at=NOW - timedelta(seconds=300),
                    stale_after_seconds=300,
                ),
            ]
        )
        db.commit()
    finally:
        generator.close()
    url = "/api/v1/connectivity/incidents"
    history = client.get(url).json()
    assert len(history) == 2
    recovered = client.get(url, params={"sensor_id": "pump", "status": "recovered"}).json()
    assert recovered[0]["duration_seconds"] == 10
    assert len(client.get(url, params={"limit": 1, "offset": 1}).json()) == 1
    assert client.get(url, params={"started_from": "2027-01-01T00:00:00Z"}).json() == []
    assert (
        len(
            client.get(
                url,
                params={
                    "metric": "pressure",
                    "started_from": "2026-10-27T14:00:00+02:00",
                    "started_to": "2026-10-27T14:00:00+02:00",
                },
            ).json()
        )
        == 1
    )
    assert client.get(url, params={"status": "invalid"}).status_code == 422
    assert client.get(url, params={"started_from": "2026-10-27T00:00:00"}).status_code == 422
    assert (
        client.get(
            url,
            params={
                "started_from": "2027-01-01T00:00:00Z",
                "started_to": "2026-01-01T00:00:00Z",
            },
        ).status_code
        == 422
    )


def test_real_monitor_command_persists_without_dashboard(sessions):
    receive(sessions, datetime.now(timezone.utc) - timedelta(seconds=400))
    env = {**os.environ, "SENSORWATCH_DATABASE_URL": str(sessions.kw["bind"].url)}
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-m", "sensorwatch", "monitor", "--once"],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
    with sessions() as db:
        assert len(db.scalars(select(ConnectivityIncident)).all()) == 1


def test_monitor_once_exit_codes_and_retry(monkeypatch, caplog):
    from sqlalchemy.exc import SQLAlchemyError

    from sensorwatch import monitor

    monkeypatch.setattr(monitor, "monitor_once", lambda _: {"opened": 1, "recovered": 0})
    assert monitor.run_monitor(once=True) == 0

    def fail(_):
        raise SQLAlchemyError("private details must not be logged")

    monkeypatch.setattr(monitor, "monitor_once", fail)
    assert monitor.run_monitor(once=True) == 1
    assert "private details" not in caplog.text

    class StopAfterWait:
        stopped = False

        def is_set(self):
            return self.stopped

        def set(self):
            self.stopped = True

        def wait(self, _):
            self.set()

    monkeypatch.setattr(monitor, "Event", StopAfterWait)
    assert monitor.run_monitor(interval=1) == 0
