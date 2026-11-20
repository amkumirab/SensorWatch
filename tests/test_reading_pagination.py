def test_readings_paginate_filtered_results_with_equal_timestamps(client):
    timestamp = "2026-11-20T12:00:00Z"
    for sensor, value in [("pump", 1), ("other", 9), ("pump", 2), ("pump", 3)]:
        response = client.post(
            "/api/v1/readings",
            json={
                "sensor_id": sensor,
                "metric": "pressure",
                "value": value,
                "recorded_at": timestamp,
            },
        )
        assert response.status_code == 201
    query = "/api/v1/readings?sensor_id=pump&metric=pressure&limit=2"
    first = client.get(query).json()
    second = client.get(query + "&offset=2").json()
    assert [row["value"] for row in first] == [3, 2]
    assert [row["value"] for row in second] == [1]
    assert client.get(query + "&offset=3").json() == []
    assert client.get(query + "&offset=-1").status_code == 422


def test_reading_pagination_applies_after_anomaly_filter(client):
    client.put("/api/v1/rules/pump/pressure", json={"upper_bound": 10})
    for value in [11, 1, 12]:
        client.post(
            "/api/v1/readings",
            json={
                "sensor_id": "pump",
                "metric": "pressure",
                "value": value,
                "recorded_at": "2026-11-20T12:00:00Z",
            },
        )
    response = client.get("/api/v1/readings?anomalies_only=true&limit=1&offset=1")
    assert response.status_code == 200
    assert [row["value"] for row in response.json()] == [11]
