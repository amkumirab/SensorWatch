from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    detector_window: int
    detector_min_samples: int
    detector_threshold: float
    demo_enabled: bool


def normalize_database_url(database_url: str) -> str:
    """Use psycopg 3 for PostgreSQL URLs, including common hosting aliases."""
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


@lru_cache
def get_settings() -> Settings:
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
    )
