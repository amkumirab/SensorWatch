from alembic import command
from sqlalchemy import inspect, text

from sensorwatch.db import make_engine
from sensorwatch.migration import alembic_config, upgrade_database


def test_heartbeat_migration_preserves_incidents_without_inventing_a_success(tmp_path):
    url = f"sqlite:///{tmp_path / 'upgrade-heartbeat.db'}"
    command.upgrade(alembic_config(url), "20261027_0005")
    engine = make_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO connectivity_incidents (sensor_id, metric, started_at, "
                "detected_at, last_received_at, stale_after_seconds) VALUES "
                "('pump', 'pressure', :now, :now, :now, 300)"
            ),
            {"now": "2026-11-07 12:00:00.000000"},
        )
    engine.dispose()
    upgrade_database(url)
    engine = make_engine(url)
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT COUNT(*) FROM monitor_heartbeats")).scalar_one()
            == 0
        )
        assert (
            connection.execute(text("SELECT COUNT(*) FROM connectivity_incidents")).scalar_one()
            == 1
        )
    engine.dispose()
    command.downgrade(alembic_config(url), "20261027_0005")
    engine = make_engine(url)
    assert "monitor_heartbeats" not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT COUNT(*) FROM connectivity_incidents")).scalar_one()
            == 1
        )
    engine.dispose()
    upgrade_database(url)
