from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from sensorwatch.api import app
from sensorwatch.config import Settings, normalize_database_url
from sensorwatch.connectivity import stream_health
from sensorwatch.db import get_db, make_engine
from sensorwatch.models import Alert, SensorReading, SensorRule
from sensorwatch.schemas import ReadingCreate
from sensorwatch.service import ReadingService

POSTGRES_URL = os.getenv("SENSORWATCH_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    POSTGRES_URL is None, reason="SENSORWATCH_TEST_POSTGRES_URL is not configured"
)


def test_postgres_migration_and_reading_round_trip() -> None:
    assert POSTGRES_URL is not None
    database_url = normalize_database_url(POSTGRES_URL)
    engine = make_engine(database_url)
    settings = Settings(
        database_url=database_url,
        detector_window=20,
        detector_min_samples=6,
        detector_threshold=3.5,
        demo_enabled=False,
    )

    assert engine.dialect.name == "postgresql"
    assert {"alembic_version", "sensor_readings", "alerts", "sensor_rules"}.issubset(
        inspect(engine).get_table_names()
    )

    with Session(engine) as session:
        service = ReadingService(session, settings)
        for value in [20.0, 20.1, 19.9, 20.05, 19.95, 20.0]:
            service.add(
                ReadingCreate(
                    sensor_id="ci-boiler", metric="temperature", value=value, unit="C"
                )
            )
        anomaly = service.add(
            ReadingCreate(sensor_id="ci-boiler", metric="temperature", value=32.0, unit="C")
        )
        assert anomaly.is_anomaly is True
        assert (
            session.scalar(select(SensorReading).where(SensorReading.id == anomaly.id))
            is anomaly
        )
        alert = session.scalar(select(Alert).where(Alert.reading_id == anomaly.id))
        assert alert is not None
        assert alert.status == "open"
        assert alert.severity == "critical"
        session.add(SensorRule(sensor_id="ci-limits", metric="pressure", upper_bound=10))
        session.flush()
        breach = service.add(ReadingCreate(sensor_id="ci-limits", metric="pressure", value=11))
        assert breach.is_anomaly is True
        assert breach.applied_rule["upper_bound"] == 10
        health = stream_health(session)
        assert health[("ci-limits", "pressure")].connectivity_status == "online"
        assert session.execute(text("SELECT 1")).scalar_one() == 1
        session.rollback()

    engine.dispose()


def test_postgres_rule_api_upsert_and_ingestion() -> None:
    assert POSTGRES_URL is not None
    engine = make_engine(normalize_database_url(POSTGRES_URL))
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:

            def override_db():
                yield session

            app.dependency_overrides[get_db] = override_db
            try:
                with TestClient(app) as client:
                    path = "/api/v1/rules/ci-api/pressure"
                    assert (
                        client.put(
                            path, json={"upper_bound": 10, "stale_after_seconds": 60}
                        ).status_code
                        == 200
                    )
                    assert (
                        client.put(
                            path, json={"upper_bound": 20, "stale_after_seconds": 120}
                        ).status_code
                        == 200
                    )
                    response = client.post(
                        "/api/v1/readings",
                        json={
                            "sensor_id": "ci-api",
                            "metric": "pressure",
                            "value": 21,
                        },
                    )
                    assert response.status_code == 201
                    assert response.json()["is_anomaly"] is True
                    assert response.json()["applied_rule"]["upper_bound"] == 20
                    health = client.get("/api/v1/sensors").json()
                    assert health[0]["stale_after_seconds"] == 120
                    assert health[0]["connectivity_status"] == "online"
                    assert client.delete(path).status_code == 204
            finally:
                app.dependency_overrides.clear()
        transaction.rollback()
    engine.dispose()
