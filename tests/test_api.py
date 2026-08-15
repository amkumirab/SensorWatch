from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_single_reading_is_persisted(client: TestClient) -> None:
    response = client.post(
        "/api/v1/readings",
        json={
            "sensor_id": "boiler-01",
            "metric": "temperature",
            "value": 70.4,
            "unit": "C",
        },
    )

    assert response.status_code == 201
    assert response.json()["detector_status"] == "warming-up"
    readings = client.get("/api/v1/readings").json()
    assert len(readings) == 1
    assert readings[0]["sensor_id"] == "boiler-01"


def test_batch_detects_spike_and_updates_summary(client: TestClient) -> None:
    baseline = [
        {
            "sensor_id": "pump-07",
            "metric": "vibration",
            "value": 2.5 + ((index % 3) - 1) * 0.03,
            "unit": "mm/s",
        }
        for index in range(16)
    ]
    payload = {"readings": [*baseline, {**baseline[-1], "value": 8.8}]}

    response = client.post("/api/v1/readings/batch", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["accepted"] == 17
    assert body["anomalies"] == 1
    assert body["readings"][-1]["is_anomaly"] is True

    summary = client.get("/api/v1/summary").json()
    assert summary["total_readings"] == 17
    assert summary["total_anomalies"] == 1
    assert summary["active_series"] == 1

    anomalies = client.get("/api/v1/readings?anomalies_only=true").json()
    assert len(anomalies) == 1
    assert anomalies[0]["anomaly_score"] >= 3.5


def test_demo_generator_creates_multiple_sensor_series(client: TestClient) -> None:
    response = client.post(
        "/api/v1/demo/generate", json={"count": 90, "seed": 7, "spike_every": 29}
    )

    assert response.status_code == 201
    assert response.json()["accepted"] == 90
    sensors = client.get("/api/v1/sensors").json()
    assert len(sensors) == 3
    assert {item["metric"] for item in sensors} == {
        "temperature",
        "vibration",
        "pressure",
    }


def test_validation_rejects_unsafe_sensor_identifier(client: TestClient) -> None:
    response = client.post(
        "/api/v1/readings",
        json={"sensor_id": "<script>", "metric": "temperature", "value": 1},
    )

    assert response.status_code == 422
