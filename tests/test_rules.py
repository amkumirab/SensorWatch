import pytest
from fastapi.testclient import TestClient

RULE = "/api/v1/rules/boiler-01/temperature"


def send(client, value, sensor_id="boiler-01", metric="temperature"):
    return client.post(
        "/api/v1/readings",
        json={
            "sensor_id": sensor_id,
            "metric": metric,
            "value": value,
        },
    )


def test_rule_crud_and_inclusive_bounds(client: TestClient):
    assert client.get(RULE).status_code == 404
    rule = {"lower_bound": 10, "upper_bound": 80, "detector_threshold": 5}
    assert client.put(RULE, json=rule).status_code == 200
    assert client.put(RULE, json=rule).status_code == 200
    assert len(client.get("/api/v1/rules").json()) == 1
    for value in (10, 80):
        assert send(client, value).json()["is_anomaly"] is False
    reading = send(client, 81).json()
    assert reading["is_anomaly"] is True
    assert reading["applied_rule"] == rule
    assert client.get("/api/v1/alerts").json()[0]["severity"] == "critical"
    assert send(client, 81, sensor_id="other").json()["is_anomaly"] is False
    assert send(client, 81, metric="pressure").json()["is_anomaly"] is False
    assert client.delete(RULE).status_code == 204
    assert client.get(RULE).status_code == 404
    assert client.delete(RULE).status_code == 404
    assert send(client, 81).json()["applied_rule"] is None
    historical = client.get("/api/v1/readings").json()
    assert (
        next(item for item in historical if item["id"] == reading["id"])["applied_rule"] == rule
    )


@pytest.mark.parametrize(
    "rule",
    [
        {"lower_bound": 5, "upper_bound": 4},
        {"lower_bound": 5, "upper_bound": 5},
        {"detector_threshold": 0},
        {"detector_threshold": -1},
        {"upper_bound": "NaN"},
        {"lower_bound": "Infinity"},
        {"detector_threshold": "Infinity"},
        {"unknown_field": 1},
    ],
)
def test_invalid_rules_are_rejected(client: TestClient, rule):
    assert client.put(RULE, json=rule).status_code == 422


def test_custom_sensitivity_and_replacement(client: TestClient):
    assert client.put(RULE, json={"detector_threshold": 100}).status_code == 200
    for _ in range(12):
        assert send(client, 20).status_code == 201
    custom = send(client, 22).json()
    assert custom["is_anomaly"] is False
    assert custom["applied_rule"]["detector_threshold"] == 100
    assert client.put(RULE, json={"upper_bound": 90}).status_code == 200
    default = send(client, 22).json()
    assert default["is_anomaly"] is True
    assert default["applied_rule"]["detector_threshold"] == 3.5


def test_lower_bound_and_batch_rules(client: TestClient):
    assert client.put(RULE, json={"lower_bound": 0}).status_code == 200
    response = client.post(
        "/api/v1/readings/batch",
        json={
            "readings": [
                {"sensor_id": "boiler-01", "metric": "temperature", "value": value}
                for value in (0, -1)
            ]
        },
    )
    assert response.status_code == 201
    assert response.json()["anomalies"] == 1


def test_rule_mutations_require_configured_key(client, monkeypatch):
    from sensorwatch.config import get_settings

    monkeypatch.setenv("SENSORWATCH_INGEST_API_KEY", "test-rules-key")
    get_settings.cache_clear()
    try:
        assert client.put(RULE, json={}).status_code == 401
        headers = {"X-API-Key": "test-rules-key"}
        assert client.put(RULE, json={}, headers=headers).status_code == 200
        assert client.get(RULE).status_code == 200
        assert client.delete(RULE).status_code == 401
        assert client.delete(RULE, headers=headers).status_code == 204
    finally:
        get_settings.cache_clear()


def test_rule_identifiers_and_pagination(client: TestClient):
    assert client.put("/api/v1/rules/bad%20id/temperature", json={}).status_code == 422
    assert client.put("/api/v1/rules/boiler-02/temperature", json={}).status_code == 200
    assert client.put(RULE, json={}).status_code == 200
    page = client.get("/api/v1/rules?limit=1&offset=1").json()
    assert len(page) == 1
    assert page[0]["sensor_id"] == "boiler-02"
    assert client.get("/api/v1/rules?offset=-1").status_code == 422
