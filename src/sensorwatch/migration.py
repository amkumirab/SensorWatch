from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from sensorwatch.config import get_settings, normalize_database_url
from sensorwatch.db import ensure_database_parent, make_engine

INITIAL_REVISION = "20260913_0001"
LEGACY_READING_COLUMNS = {
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


def alembic_config(database_url: str | None = None) -> Config:
    configured_url = normalize_database_url(database_url or get_settings().database_url)
    ensure_database_parent(configured_url)

    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parent / "migrations")
    )
    config.set_main_option("sqlalchemy.url", configured_url.replace("%", "%%"))
    config.attributes["database_url"] = configured_url
    return config


def upgrade_database(database_url: str | None = None) -> None:
    config = alembic_config(database_url)
    configured_url = config.attributes["database_url"]
    engine = make_engine(configured_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        if "sensor_readings" in tables and "alembic_version" not in tables:
            columns = {
                column["name"] for column in inspector.get_columns("sensor_readings")
            }
            missing_columns = LEGACY_READING_COLUMNS - columns
            if missing_columns:
                missing = ", ".join(sorted(missing_columns))
                raise RuntimeError(
                    "The existing sensor_readings table is not compatible with the "
                    f"initial migration; missing columns: {missing}"
                )
            command.stamp(config, INITIAL_REVISION)
    finally:
        engine.dispose()

    command.upgrade(config, "head")
