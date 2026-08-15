from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReadingCreate(BaseModel):
    sensor_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    metric: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    value: float
    unit: str = Field(default="", max_length=24)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: float) -> float:
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError("value must be finite")
        return value


class ReadingBatchCreate(BaseModel):
    readings: list[ReadingCreate] = Field(min_length=1, max_length=500)


class ReadingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sensor_id: str
    metric: str
    value: float
    unit: str
    recorded_at: datetime
    anomaly_score: float
    is_anomaly: bool
    detector_status: str
    baseline_center: float | None
    baseline_scale: float | None


class BatchResponse(BaseModel):
    accepted: int
    anomalies: int
    readings: list[ReadingResponse]


class SensorSeriesSummary(BaseModel):
    sensor_id: str
    metric: str
    unit: str
    total_readings: int
    anomaly_count: int
    last_value: float
    last_recorded_at: datetime


class OverviewResponse(BaseModel):
    total_readings: int
    total_anomalies: int
    anomaly_rate: float
    active_series: int
    latest_recorded_at: datetime | None


class DemoGenerateRequest(BaseModel):
    count: int = Field(default=180, ge=20, le=500)
    seed: int = Field(default=42, ge=0, le=1_000_000)
    spike_every: int = Field(default=37, ge=10, le=200)
