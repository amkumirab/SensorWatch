from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from sensorwatch.config import get_settings


@pytest.fixture
def protected_client(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("SENSORWATCH_INGEST_API_KEY", "test-ingest-key")
    get_settings.cache_clear()
    yield client
    get_settings.cache_clear()


def reading_payload() -> dict[str, object]:
    return {
        "sensor_id": "boiler-01",
        "metric": "temperature",
        "value": 70.4,
        "unit": "C",
    }


def test_ingestion_rejects_missing_and_invalid_api_keys(
    protected_client: TestClient,
) -> None:
    missing = protected_client.post("/api/v1/readings", json=reading_payload())
    invalid = protected_client.post(
        "/api/v1/readings",
        json=reading_payload(),
        headers={"X-API-Key": "wrong-key"},
    )

    for response in (missing, invalid):
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid or missing API key"}
        assert response.headers["www-authenticate"] == "ApiKey"


def test_valid_api_key_allows_single_and_batch_ingestion(
    protected_client: TestClient,
) -> None:
    headers = {"X-API-Key": "test-ingest-key"}

    single = protected_client.post(
        "/api/v1/readings", json=reading_payload(), headers=headers
    )
    batch = protected_client.post(
        "/api/v1/readings/batch",
        json={"readings": [{**reading_payload(), "value": 71.2}]},
        headers=headers,
    )

    assert single.status_code == 201
    assert batch.status_code == 201
    assert batch.json()["accepted"] == 1


def test_demo_generation_requires_api_key_when_authentication_is_enabled(
    protected_client: TestClient,
) -> None:
    payload = {"count": 20, "seed": 7, "spike_every": 10}

    unauthorized = protected_client.post("/api/v1/demo/generate", json=payload)
    authorized = protected_client.post(
        "/api/v1/demo/generate",
        json=payload,
        headers={"X-API-Key": "test-ingest-key"},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 201


def test_read_endpoints_remain_public_when_ingestion_is_protected(
    protected_client: TestClient,
) -> None:
    assert protected_client.get("/health").status_code == 200
    assert protected_client.get("/api/v1/readings").status_code == 200
    assert protected_client.get("/api/v1/summary").status_code == 200


def test_openapi_documents_api_key_security(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    security_scheme = schema["components"]["securitySchemes"]["APIKeyHeader"]

    assert security_scheme == {"type": "apiKey", "in": "header", "name": "X-API-Key"}
    assert schema["paths"]["/api/v1/readings"]["post"]["security"] == [
        {"APIKeyHeader": []}
    ]
    assert "security" not in schema["paths"]["/api/v1/readings"]["get"]
