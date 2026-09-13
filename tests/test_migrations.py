from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from sensorwatch.db import Base, make_engine
from sensorwatch.migration import upgrade_database
from sensorwatch.models import SensorReading


def test_initial_migration_creates_expected_schema(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"

    upgrade_database(database_url)
    upgrade_database(database_url)

    engine = make_engine(database_url)
    inspector = inspect(engine)
    assert {"alembic_version", "sensor_readings"}.issubset(inspector.get_table_names())
    assert {column["name"] for column in inspector.get_columns("sensor_readings")} == {
        "id",
        "sensor_id",
        "metric",
        "value",
        "unit",
        "recorded_at",
        "anomaly_score",
        "is_anomaly",
        "detector_status",
        "baseline_center",
        "baseline_scale",
        "created_at",
    }
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert revision == "20260913_0001"
    engine.dispose()


def test_migration_stamps_legacy_schema_without_losing_data(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = make_engine(database_url)
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        session.add(
            SensorReading(
                sensor_id="legacy-boiler",
                metric="temperature",
                value=72.0,
                unit="C",
                recorded_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
    engine.dispose()

    upgrade_database(database_url)

    migrated_engine = make_engine(database_url)
    with migrated_engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        reading_count = connection.execute(
            text("SELECT COUNT(*) FROM sensor_readings")
        ).scalar_one()
    assert revision == "20260913_0001"
    assert reading_count == 1
    migrated_engine.dispose()
