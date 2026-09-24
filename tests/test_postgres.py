from __future__ import annotations

import os

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from sensorwatch.config import Settings, normalize_database_url
from sensorwatch.db import make_engine
from sensorwatch.models import Alert, SensorReading
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
    assert {"alembic_version", "sensor_readings", "alerts"}.issubset(
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
            ReadingCreate(
                sensor_id="ci-boiler", metric="temperature", value=32.0, unit="C"
            )
        )
        assert anomaly.is_anomaly is True
        assert session.scalar(
            select(SensorReading).where(SensorReading.id == anomaly.id)
        ) is anomaly
        alert = session.scalar(select(Alert).where(Alert.reading_id == anomaly.id))
        assert alert is not None
        assert alert.status == "open"
        assert alert.severity == "critical"
        assert session.execute(text("SELECT 1")).scalar_one() == 1
        session.rollback()

    engine.dispose()
