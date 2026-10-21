from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sensorwatch import connectivity
from sensorwatch.config import Settings
from sensorwatch.db import Base
from sensorwatch.schemas import ReadingCreate
from sensorwatch.service import ReadingService, series_summaries


@pytest.mark.parametrize(
    "age, expected", [(299.999, "online"), (300, "online"), (300.001, "stale"), (-1, "online")]
)
def test_freshness_uses_server_receipt_time(tmp_path, monkeypatch, age, expected):
    engine = create_engine(f"sqlite:///{tmp_path / 'health.db'}")
    Base.metadata.create_all(engine)
    received = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(connectivity, "utc_now", lambda: received + timedelta(seconds=age))
    settings = Settings("sqlite://", 40, 12, 3.5, False)
    with Session(engine) as db:
        service = ReadingService(db, settings)
        row = service.add(
            ReadingCreate(
                sensor_id="pump",
                metric="pressure",
                value=2,
                recorded_at=received + timedelta(days=100),
            )
        )
        row.created_at = received
        db.commit()
        summary = series_summaries(db)[0]
        assert summary.connectivity_status == expected
        assert summary.last_received_at == received
        assert summary.stale_after_seconds == 300
    engine.dispose()


def test_custom_timeout_summary_and_recovery(client, monkeypatch):
    path = "/api/v1/rules/pump/pressure"
    assert client.put(path, json={"stale_after_seconds": 60}).status_code == 200
    assert client.get(path).json()["stale_after_seconds"] == 60
    payload = {
        "sensor_id": "pump",
        "metric": "pressure",
        "value": 2,
        "recorded_at": "2000-01-01T00:00:00Z",
    }
    assert client.post("/api/v1/readings", json=payload).status_code == 201
    assert (
        client.post("/api/v1/readings", json={**payload, "sensor_id": "other"}).status_code
        == 201
    )
    future = datetime.now(timezone.utc) + timedelta(seconds=61)
    monkeypatch.setattr(connectivity, "utc_now", lambda: future)
    sensors = client.get("/api/v1/sensors").json()
    assert {row["sensor_id"]: row["connectivity_status"] for row in sensors} == {
        "other": "online",
        "pump": "stale",
    }
    assert client.get("/api/v1/summary").json()["stale_series"] == 1
    monkeypatch.setattr(connectivity, "utc_now", lambda: datetime.now(timezone.utc))
    assert client.post("/api/v1/readings", json=payload).status_code == 201
    assert client.get("/api/v1/summary").json()["stale_series"] == 0
    assert client.get("/api/v1/alerts").json() == []


@pytest.mark.parametrize("value", [0, -1, 1.5, "NaN", "Infinity", 604801])
def test_timeout_validation(client, value):
    assert (
        client.put(
            "/api/v1/rules/pump/pressure",
            json={
                "stale_after_seconds": value,
            },
        ).status_code
        == 422
    )


def test_override_changes_and_empty_fleet(client, monkeypatch):
    assert client.get("/api/v1/summary").json()["stale_series"] == 0
    path = "/api/v1/rules/pump/pressure"
    assert client.put(path, json={"stale_after_seconds": 30}).status_code == 200
    assert client.get("/api/v1/sensors").json() == []
    client.post(
        "/api/v1/readings", json={"sensor_id": "pump", "metric": "pressure", "value": 2}
    )
    now = datetime.now(timezone.utc) + timedelta(seconds=31)
    monkeypatch.setattr(connectivity, "utc_now", lambda: now)
    assert client.get("/api/v1/summary").json()["stale_series"] == 1
    assert client.put(path, json={"stale_after_seconds": None}).status_code == 200
    assert client.get("/api/v1/summary").json()["stale_series"] == 0


def test_timeout_is_specific_to_metric(client, monkeypatch):
    for metric in ("pressure", "temperature"):
        response = client.post(
            "/api/v1/readings",
            json={
                "sensor_id": "pump",
                "metric": metric,
                "value": 2,
            },
        )
        assert response.status_code == 201
    assert (
        client.put(
            "/api/v1/rules/pump/pressure",
            json={
                "stale_after_seconds": 60,
            },
        ).status_code
        == 200
    )
    now = datetime.now(timezone.utc) + timedelta(seconds=61)
    monkeypatch.setattr(connectivity, "utc_now", lambda: now)
    health = client.get("/api/v1/sensors").json()
    assert {item["metric"]: item["connectivity_status"] for item in health} == {
        "pressure": "stale",
        "temperature": "online",
    }
