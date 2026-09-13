from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from sensorwatch.config import get_settings


class Base(DeclarativeBase):
    pass


def ensure_database_parent(database_url: str) -> None:
    if database_url.startswith("sqlite:///"):
        database_path = database_url.removeprefix("sqlite:///")
        if database_path != ":memory:":
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)


def make_engine(database_url: str) -> Engine:
    ensure_database_parent(database_url)
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)


settings = get_settings()
engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=True, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
