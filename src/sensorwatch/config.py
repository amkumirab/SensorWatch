from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    detector_window: int
    detector_min_samples: int
    detector_threshold: float
    demo_enabled: bool
    ingest_api_key_digest: bytes | None


def digest_api_key(api_key: str) -> bytes:
    """Create a fixed-size fingerprint without retaining the plaintext key."""
    return sha256(api_key.encode("utf-8")).digest()


def normalize_database_url(database_url: str) -> str:
    """Use psycopg 3 for PostgreSQL URLs, including common hosting aliases."""
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


@lru_cache
def get_settings() -> Settings:
    ingest_api_key = os.getenv("SENSORWATCH_INGEST_API_KEY", "")
    return Settings(
        database_url=normalize_database_url(
            os.getenv("SENSORWATCH_DATABASE_URL", "sqlite:///./data/sensorwatch.db")
        ),
        detector_window=int(os.getenv("SENSORWATCH_DETECTOR_WINDOW", "40")),
        detector_min_samples=int(
            os.getenv("SENSORWATCH_DETECTOR_MIN_SAMPLES", "12")
        ),
        detector_threshold=float(
            os.getenv("SENSORWATCH_DETECTOR_THRESHOLD", "3.5")
        ),
        demo_enabled=os.getenv("SENSORWATCH_DEMO_ENABLED", "true").lower()
        in {"1", "true", "yes", "on"},
        ingest_api_key_digest=(
            digest_api_key(ingest_api_key) if ingest_api_key else None
        ),
    )
