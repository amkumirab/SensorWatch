from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from sensorwatch.config import get_settings
from sensorwatch.db import get_db, init_db
from sensorwatch.demo import generate_demo_readings
from sensorwatch.schemas import (
    BatchResponse,
    DemoGenerateRequest,
    OverviewResponse,
    ReadingBatchCreate,
    ReadingCreate,
    ReadingResponse,
    SensorSeriesSummary,
)
from sensorwatch.service import ReadingService, list_readings, overview, series_summaries

STATIC_DIR = Path(__file__).parent / "static"
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(
    title="SensorWatch API",
    version="0.1.0",
    description="Streaming sensor ingestion and robust rolling anomaly detection.",
    lifespan=lifespan,
)
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

Database = Annotated[Session, Depends(get_db)]


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health(db: Database) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post("/api/v1/readings", response_model=ReadingResponse, status_code=201)
def create_reading(payload: ReadingCreate, db: Database) -> ReadingResponse:
    row = ReadingService(db, settings).add(payload)
    db.commit()
    db.refresh(row)
    return ReadingResponse.model_validate(row)


@app.post("/api/v1/readings/batch", response_model=BatchResponse, status_code=201)
def create_reading_batch(payload: ReadingBatchCreate, db: Database) -> BatchResponse:
    service = ReadingService(db, settings)
    rows = [service.add(reading) for reading in payload.readings]
    db.commit()
    return BatchResponse(
        accepted=len(rows),
        anomalies=sum(row.is_anomaly for row in rows),
        readings=[ReadingResponse.model_validate(row) for row in rows],
    )


@app.get("/api/v1/readings", response_model=list[ReadingResponse])
def get_readings(
    db: Database,
    sensor_id: str | None = None,
    metric: str | None = None,
    anomalies_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[ReadingResponse]:
    return [
        ReadingResponse.model_validate(row)
        for row in list_readings(
            db,
            sensor_id=sensor_id,
            metric=metric,
            anomalies_only=anomalies_only,
            limit=limit,
        )
    ]


@app.get("/api/v1/summary", response_model=OverviewResponse)
def get_summary(db: Database) -> OverviewResponse:
    return overview(db)


@app.get("/api/v1/sensors", response_model=list[SensorSeriesSummary])
def get_sensors(db: Database) -> list[SensorSeriesSummary]:
    return series_summaries(db)


@app.post("/api/v1/demo/generate", response_model=BatchResponse, status_code=201)
def generate_demo(payload: DemoGenerateRequest, db: Database) -> BatchResponse:
    if not settings.demo_enabled:
        raise HTTPException(status_code=404, detail="Demo generation is disabled")
    service = ReadingService(db, settings)
    rows = [
        service.add(reading)
        for reading in generate_demo_readings(
            count=payload.count, seed=payload.seed, spike_every=payload.spike_every
        )
    ]
    db.commit()
    return BatchResponse(
        accepted=len(rows),
        anomalies=sum(row.is_anomaly for row in rows),
        readings=[ReadingResponse.model_validate(row) for row in rows],
    )
