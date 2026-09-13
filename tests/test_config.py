from sensorwatch.config import normalize_database_url


def test_normalize_database_url_selects_psycopg_driver() -> None:
    assert (
        normalize_database_url("postgres://user:pass@db.example/sensorwatch")
        == "postgresql+psycopg://user:pass@db.example/sensorwatch"
    )
    assert (
        normalize_database_url("postgresql://user:pass@localhost/sensorwatch")
        == "postgresql+psycopg://user:pass@localhost/sensorwatch"
    )


def test_normalize_database_url_preserves_explicit_driver_and_sqlite() -> None:
    explicit = "postgresql+psycopg://user:pass@localhost/sensorwatch"
    sqlite = "sqlite:///./data/sensorwatch.db"

    assert normalize_database_url(explicit) == explicit
    assert normalize_database_url(sqlite) == sqlite
