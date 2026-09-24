from fastapi.testclient import TestClient


def anomaly_payload(spike: float = 8.8) -> dict[str, list[dict[str, object]]]:
    baseline = [
        {
            "sensor_id": "pump-07",
            "metric": "vibration",
            "value": 2.5 + ((index % 3) - 1) * 0.03,
            "unit": "mm/s",
        }
        for index in range(16)
    ]
    return {"readings": [*baseline, {**baseline[-1], "value": spike}]}


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
    response = client.post("/api/v1/readings/batch", json=anomaly_payload())

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


def test_alert_lifecycle_enforces_state_transitions(client: TestClient) -> None:
    ingestion = client.post("/api/v1/readings/batch", json=anomaly_payload())
    assert ingestion.status_code == 201

    alerts = client.get("/api/v1/alerts?active_only=true").json()
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["status"] == "open"
    assert alert["severity"] == "critical"
    assert alert["reading"]["sensor_id"] == "pump-07"
    assert alert["reading"]["is_anomaly"] is True

    premature_resolution = client.post(
        f"/api/v1/alerts/{alert['id']}/resolve", json={"operator": "night-shift"}
    )
    assert premature_resolution.status_code == 409

    acknowledgement = client.post(
        f"/api/v1/alerts/{alert['id']}/acknowledge",
        json={"operator": "night-shift"},
    )
    assert acknowledgement.status_code == 200
    acknowledged = acknowledgement.json()
    assert acknowledged["status"] == "acknowledged"
    assert acknowledged["acknowledged_by"] == "night-shift"
    assert acknowledged["acknowledged_at"] is not None

    repeated_acknowledgement = client.post(
        f"/api/v1/alerts/{alert['id']}/acknowledge",
        json={"operator": "another-operator"},
    )
    assert repeated_acknowledgement.status_code == 200
    assert repeated_acknowledgement.json()["acknowledged_by"] == "night-shift"

    resolution = client.post(
        f"/api/v1/alerts/{alert['id']}/resolve", json={"operator": "day-shift"}
    )
    assert resolution.status_code == 200
    resolved = resolution.json()
    assert resolved["status"] == "resolved"
    assert resolved["resolved_by"] == "day-shift"
    assert resolved["resolved_at"] is not None

    assert client.get("/api/v1/alerts?active_only=true").json() == []
    assert len(client.get("/api/v1/alerts?status=resolved").json()) == 1

    invalid_acknowledgement = client.post(
        f"/api/v1/alerts/{alert['id']}/acknowledge",
        json={"operator": "night-shift"},
    )
    assert invalid_acknowledgement.status_code == 409


def test_alert_endpoints_validate_filters_and_operators(client: TestClient) -> None:
    response = client.post("/api/v1/readings/batch", json=anomaly_payload(spike=2.7))
    assert response.status_code == 201
    warning_alerts = client.get("/api/v1/alerts?severity=warning").json()
    assert len(warning_alerts) == 1
    assert client.get("/api/v1/alerts?severity=critical").json() == []

    assert client.get("/api/v1/alerts?status=invalid").status_code == 422
    assert client.get("/api/v1/alerts?severity=invalid").status_code == 422
    assert client.post(
        "/api/v1/alerts/999/acknowledge", json={"operator": "operator"}
    ).status_code == 404
    assert client.post(
        "/api/v1/alerts/999/resolve", json={"operator": "operator"}
    ).status_code == 404
    assert client.post(
        "/api/v1/alerts/999/acknowledge", json={"operator": "   "}
    ).status_code == 422


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
