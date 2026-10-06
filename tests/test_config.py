from sensorwatch.config import Settings, get_settings, normalize_database_url


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


def test_settings_store_only_an_api_key_digest(monkeypatch) -> None:
    raw_key = "test-ingest-key"
    monkeypatch.setenv("SENSORWATCH_INGEST_API_KEY", raw_key)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.ingest_api_key_digest is not None
    assert isinstance(settings.ingest_api_key_digest, bytes)
    assert raw_key.encode() not in settings.ingest_api_key_digest
    assert not hasattr(settings, "ingest_api_key")
    get_settings.cache_clear()


def test_settings_keep_authentication_optional_for_direct_construction() -> None:
    settings = Settings(
        database_url="sqlite://",
        detector_window=20,
        detector_min_samples=6,
        detector_threshold=3.5,
        demo_enabled=False,
    )

    assert settings.ingest_api_key_digest is None
