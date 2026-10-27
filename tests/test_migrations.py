from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from sensorwatch.db import make_engine
from sensorwatch.migration import alembic_config, upgrade_database


def test_initial_migration_creates_expected_schema(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"

    upgrade_database(database_url)
    upgrade_database(database_url)

    engine = make_engine(database_url)
    inspector = inspect(engine)
    assert {"alembic_version", "sensor_readings", "alerts", "sensor_rules"}.issubset(
        inspector.get_table_names()
    )
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
        "applied_rule",
        "created_at",
    }
    assert {column["name"] for column in inspector.get_columns("alerts")} == {
        "id",
        "reading_id",
        "severity",
        "status",
        "message",
        "created_at",
        "acknowledged_at",
        "acknowledged_by",
        "resolved_at",
        "resolved_by",
    }
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert revision == "20261027_0005"
    engine.dispose()


def test_migration_stamps_legacy_schema_without_losing_data(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    command.upgrade(alembic_config(database_url), "20260913_0001")
    engine = make_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
        connection.execute(
            text(
                "INSERT INTO sensor_readings (sensor_id, metric, value, unit, recorded_at, "
                "anomaly_score, is_anomaly, detector_status, created_at) VALUES "
                "('legacy-boiler', 'temperature', 72, 'C', :now, 0, false, 'warming-up', :now)"
            ),
            {"now": datetime.now(timezone.utc).isoformat()},
        )
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
    assert revision == "20261027_0005"
    assert reading_count == 1
    migrated_engine.dispose()


def test_rule_migration_can_be_rolled_back_and_reapplied(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'rollback.db'}"
    upgrade_database(url)
    command.downgrade(alembic_config(url), "20260924_0002")
    engine = make_engine(url)
    assert "sensor_rules" not in inspect(engine).get_table_names()
    assert "applied_rule" not in {
        column["name"] for column in inspect(engine).get_columns("sensor_readings")
    }
    engine.dispose()
    upgrade_database(url)


def test_stream_timeout_migration_preserves_rules(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'timeout.db'}"
    command.upgrade(alembic_config(url), "20261016_0003")
    engine = make_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO sensor_rules (sensor_id, metric, upper_bound) "
                "VALUES ('pump', 'pressure', 80)"
            )
        )
    engine.dispose()
    upgrade_database(url)
    engine = make_engine(url)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT upper_bound, stale_after_seconds FROM sensor_rules")
        ).one() == (80, None)
    engine.dispose()
    command.downgrade(alembic_config(url), "20261016_0003")
    engine = make_engine(url)
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT upper_bound FROM sensor_rules")).scalar_one() == 80
        )
    engine.dispose()
    upgrade_database(url)


def test_incident_migration_enforces_one_open_record(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'incident-migration.db'}"
    upgrade_database(url)
    engine = make_engine(url)
    statement = text(
        "INSERT INTO connectivity_incidents (sensor_id, metric, started_at, detected_at, "
        "last_received_at, stale_after_seconds) VALUES "
        "('pump', 'pressure', :now, :now, :now, 300)"
    )
    with engine.begin() as connection:
        connection.execute(statement, {"now": "2026-10-27 12:00:00.000000"})
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(statement, {"now": "2026-10-27 12:00:01.000000"})
    engine.dispose()
    command.downgrade(alembic_config(url), "20261021_0004")
    engine = make_engine(url)
    assert "connectivity_incidents" not in inspect(engine).get_table_names()
    engine.dispose()
    upgrade_database(url)
