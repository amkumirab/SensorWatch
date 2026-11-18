from datetime import datetime, timezone

import pytest
from alembic import command
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sensorwatch.db import make_engine
from sensorwatch.migration import alembic_config, upgrade_database
from sensorwatch.models import SensorReading


def test_event_migration_preserves_existing_readings_and_enforces_scoped_uniqueness(tmp_path):
    url = f"sqlite:///{tmp_path / 'events.db'}"
    config = alembic_config(url)
    command.upgrade(config, "20261107_0006")
    engine = make_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO sensor_readings (id, sensor_id, metric, value, unit, recorded_at, "
                "anomaly_score, is_anomaly, detector_status, created_at) VALUES "
                "(1, 'pump', 'pressure', 12, 'bar', '2026-11-18 12:00:00', "
                "9, true, 'anomaly', '2026-11-18 12:00:01')"
            )
        )
    engine.dispose()
    upgrade_database(url)
    engine = make_engine(url)
    values = {
        "sensor_id": "pump",
        "metric": "pressure",
        "value": 12,
        "recorded_at": datetime.now(timezone.utc),
    }
    with Session(engine) as db:
        legacy = db.get(SensorReading, 1)
        assert (legacy.value, legacy.anomaly_score, legacy.is_anomaly) == (12, 9, True)
        assert (legacy.event_id, legacy.request_digest) == (None, None)
        db.add_all(
            [
                SensorReading(**values),
                SensorReading(**values),
                SensorReading(**values, event_id="evt", request_digest="a" * 64),
                SensorReading(**(values | {"metric": "temperature"}), event_id="evt"),
            ]
        )
        db.commit()
    with pytest.raises(IntegrityError), Session(engine) as db:
        db.add(SensorReading(**values, event_id="evt", request_digest="b" * 64))
        db.commit()
    engine.dispose()
    command.downgrade(config, "20261107_0006")
    engine = make_engine(url)
    assert "event_id" not in {
        column["name"] for column in inspect(engine).get_columns("sensor_readings")
    }
    engine.dispose()
    upgrade_database(url)
    engine = make_engine(url)
    with Session(engine) as db:
        rows = db.scalars(select(SensorReading)).all()
        assert len(rows) == 5
        assert all(row.event_id is None for row in rows)
        assert db.get(SensorReading, 1).anomaly_score == 9
    engine.dispose()
