from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi import Path as ApiPath
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from sensorwatch.auth import require_ingest_api_key
from sensorwatch.config import get_settings
from sensorwatch.db import get_db
from sensorwatch.demo import generate_demo_readings
from sensorwatch.models import SensorRule
from sensorwatch.schemas import (
    AlertResponse,
    AlertTransitionRequest,
    BatchResponse,
    DemoGenerateRequest,
    OverviewResponse,
    ReadingBatchCreate,
    ReadingCreate,
    ReadingResponse,
    RuleResponse,
    RuleSettings,
    SensorSeriesSummary,
)
from sensorwatch.service import (
    AlertStateError,
    ReadingService,
    acknowledge_alert,
    list_alerts,
    list_readings,
    overview,
    resolve_alert,
    series_summaries,
)

STATIC_DIR = Path(__file__).parent / "static"
settings = get_settings()


app = FastAPI(
    title="SensorWatch API",
    version="0.5.0",
    description="Streaming sensor ingestion and robust rolling anomaly detection.",
)
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

Database = Annotated[Session, Depends(get_db)]
SeriesIdentifier = Annotated[
    str, ApiPath(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
]


@app.get("/api/v1/rules", response_model=list[RuleResponse])
def get_rules(
    db: Database,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SensorRule]:
    return list(
        db.scalars(
            select(SensorRule)
            .order_by(SensorRule.sensor_id, SensorRule.metric)
            .offset(offset)
            .limit(limit)
        ).all()
    )


@app.get("/api/v1/rules/{sensor_id}/{metric}", response_model=RuleResponse)
def get_rule(sensor_id: SeriesIdentifier, metric: SeriesIdentifier, db: Database) -> SensorRule:
    rule = db.get(SensorRule, (sensor_id, metric))
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@app.put(
    "/api/v1/rules/{sensor_id}/{metric}",
    response_model=RuleResponse,
    dependencies=[Depends(require_ingest_api_key)],
)
def put_rule(
    sensor_id: SeriesIdentifier, metric: SeriesIdentifier, payload: RuleSettings, db: Database
) -> SensorRule:
    insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else postgres_insert
    statement = insert(SensorRule).values(
        sensor_id=sensor_id, metric=metric, **payload.model_dump()
    )
    db.execute(
        statement.on_conflict_do_update(
            index_elements=["sensor_id", "metric"], set_=payload.model_dump()
        )
    )
    db.commit()
    return get_rule(sensor_id, metric, db)


@app.delete(
    "/api/v1/rules/{sensor_id}/{metric}",
    status_code=204,
    dependencies=[Depends(require_ingest_api_key)],
)
def delete_rule(
    sensor_id: SeriesIdentifier, metric: SeriesIdentifier, db: Database
) -> Response:
    rule = get_rule(sensor_id, metric, db)
    db.delete(rule)
    db.commit()
    return Response(status_code=204)


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health(db: Database) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post(
    "/api/v1/readings",
    response_model=ReadingResponse,
    status_code=201,
    dependencies=[Depends(require_ingest_api_key)],
)
def create_reading(payload: ReadingCreate, db: Database) -> ReadingResponse:
    row = ReadingService(db, settings).add(payload)
    db.commit()
    db.refresh(row)
    return ReadingResponse.model_validate(row)


@app.post(
    "/api/v1/readings/batch",
    response_model=BatchResponse,
    status_code=201,
    dependencies=[Depends(require_ingest_api_key)],
)
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


@app.get("/api/v1/alerts", response_model=list[AlertResponse])
def get_alerts(
    db: Database,
    status: Annotated[str | None, Query(pattern="^(open|acknowledged|resolved)$")] = None,
    severity: Annotated[str | None, Query(pattern="^(warning|critical)$")] = None,
    active_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AlertResponse]:
    return [
        AlertResponse.model_validate(alert)
        for alert in list_alerts(
            db,
            status=status,
            severity=severity,
            active_only=active_only,
            limit=limit,
        )
    ]


@app.post("/api/v1/alerts/{alert_id}/acknowledge", response_model=AlertResponse)
def acknowledge(alert_id: int, payload: AlertTransitionRequest, db: Database) -> AlertResponse:
    try:
        alert = acknowledge_alert(db, alert_id, payload.operator)
    except AlertStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    db.commit()
    db.refresh(alert)
    return AlertResponse.model_validate(alert)


@app.post("/api/v1/alerts/{alert_id}/resolve", response_model=AlertResponse)
def resolve(alert_id: int, payload: AlertTransitionRequest, db: Database) -> AlertResponse:
    try:
        alert = resolve_alert(db, alert_id, payload.operator)
    except AlertStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    db.commit()
    db.refresh(alert)
    return AlertResponse.model_validate(alert)


@app.post(
    "/api/v1/demo/generate",
    response_model=BatchResponse,
    status_code=201,
    dependencies=[Depends(require_ingest_api_key)],
)
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
