from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from sensorwatch.db import Base
from sensorwatch.heartbeat import monitor_health
from sensorwatch.incidents import monitor_once
from sensorwatch.models import ConnectivityIncident, MonitorHeartbeat, SensorReading

NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)


@pytest.fixture
def sessions(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'heartbeat.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def test_not_started_health_does_not_break_api_liveness(client):
    response = client.get("/api/v1/monitor/health")
    assert response.status_code == 503
    assert response.json()["status"] == "not_started"
    assert response.json()["last_success_at"] is None
    assert response.json()["last_opened_incidents"] is None
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize(
    "age, expected", [(-1, "healthy"), (60, "healthy"), (60.001, "delayed")]
)
def test_successful_check_health_boundary(sessions, age, expected):
    assert monitor_once(sessions, now=NOW) == {"opened": 0, "recovered": 0}
    with sessions() as db:
        health = monitor_health(db, now=NOW + timedelta(seconds=age))
        assert health.status == expected
        assert health.last_success_at == NOW
        assert health.age_seconds == max(0, age)
        assert health.last_opened_incidents == 0
        assert health.last_recovered_incidents == 0


def test_long_check_intervals_get_proportionate_grace(sessions):
    monitor_once(sessions, now=NOW, interval_seconds=300)
    with sessions() as db:
        health = monitor_health(db, now=NOW + timedelta(seconds=900))
        assert health.status == "healthy"
        assert health.timeout_seconds == 900
        assert health.interval_seconds == 300
        assert monitor_health(db, now=NOW + timedelta(seconds=901)).status == "delayed"


@pytest.mark.parametrize("previous_success", [False, True])
def test_failed_commit_does_not_advance_heartbeat_or_incidents(
    sessions, monkeypatch, previous_success
):
    if previous_success:
        monitor_once(sessions, now=NOW)
    with sessions.begin() as db:
        db.add(
            SensorReading(
                sensor_id="pump",
                metric="pressure",
                value=2,
                unit="bar",
                recorded_at=NOW,
                created_at=NOW - timedelta(seconds=400),
            )
        )

    def fail_commit(_):
        raise SQLAlchemyError("simulated commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(sessions.class_, "commit", fail_commit)
        with pytest.raises(SQLAlchemyError):
            monitor_once(sessions, now=NOW + timedelta(seconds=1), interval_seconds=300)
    with sessions() as db:
        health = monitor_health(db, now=NOW)
        assert health.last_success_at == (NOW if previous_success else None)
        assert health.interval_seconds == (15 if previous_success else None)
        assert db.scalars(select(ConnectivityIncident)).all() == []
    assert monitor_once(sessions, now=NOW + timedelta(seconds=2))["opened"] == 1
    with sessions() as db:
        health = monitor_health(db, now=NOW + timedelta(seconds=2))
        assert health.last_success_at == NOW + timedelta(seconds=2)
        assert health.last_opened_incidents == 1
        assert len(db.scalars(select(MonitorHeartbeat)).all()) == 1


def test_api_reports_delay_and_recovery_without_mutating_heartbeat(client, monkeypatch):
    from sensorwatch import heartbeat
    from sensorwatch.api import app
    from sensorwatch.db import get_db

    generator = app.dependency_overrides[get_db]()
    db = next(generator)
    try:
        db.add(
            MonitorHeartbeat(
                id=1,
                last_success_at=NOW,
                interval_seconds=15,
                opened_incidents=2,
                recovered_incidents=1,
            )
        )
        db.commit()
        monkeypatch.setattr(heartbeat, "utc_now", lambda: NOW)
        healthy = client.get("/api/v1/monitor/health")
        assert healthy.status_code == 200
        assert healthy.json()["last_opened_incidents"] == 2
        monkeypatch.setattr(heartbeat, "utc_now", lambda: NOW + timedelta(seconds=61))
        assert client.get("/api/v1/monitor/health").status_code == 503
        db.get(MonitorHeartbeat, 1).last_success_at = NOW + timedelta(seconds=61)
        db.commit()
        assert client.get("/api/v1/monitor/health").json()["status"] == "healthy"
    finally:
        generator.close()


def test_custom_health_timeout(sessions, monkeypatch):
    from sensorwatch.config import get_settings

    monkeypatch.setenv("SENSORWATCH_MONITOR_HEALTH_TIMEOUT_SECONDS", "120")
    get_settings.cache_clear()
    try:
        monitor_once(sessions, now=NOW)
        with sessions() as db:
            health = monitor_health(db, now=NOW + timedelta(seconds=61))
            assert health.timeout_seconds == 120
            assert health.status == "healthy"
    finally:
        get_settings.cache_clear()


def test_monitor_records_its_configured_interval(monkeypatch):
    from sensorwatch import monitor

    intervals = []

    def check(_, *, interval_seconds):
        intervals.append(interval_seconds)
        return {"opened": 0, "recovered": 0}

    monkeypatch.setattr(monitor, "monitor_once", check)
    assert monitor.run_monitor(interval=120, once=True) == 0
    assert intervals == [120]


@pytest.mark.parametrize("interval", [0, -1, 3601])
def test_invalid_check_interval_is_rejected(sessions, interval):
    with pytest.raises(ValueError):
        monitor_once(sessions, interval_seconds=interval)
