import pytest


def test_reading_time_filters_include_boundaries_before_pagination(client):
    path = "/api/v1/readings"
    for value, timestamp in enumerate(
        [
            "2026-11-24T09:59:59Z",
            "2026-11-24T11:00:00+01:00",
            "2026-11-24T10:30:00Z",
            "2026-11-24T10:30:01Z",
        ]
    ):
        response = client.post(
            path,
            json={
                "sensor_id": "pump",
                "metric": "pressure",
                "value": value,
                "recorded_at": timestamp,
            },
        )
        assert response.status_code == 201

    bounds = {
        "recorded_from": "2026-11-24T12:00:00+02:00",
        "recorded_to": "2026-11-24T10:30:00Z",
    }
    for params, expected in [
        (bounds, [2, 1]),
        (bounds | {"limit": 1, "offset": 1}, [1]),
        ({"recorded_from": bounds["recorded_from"]}, [3, 2, 1]),
        ({"recorded_to": bounds["recorded_to"]}, [2, 1, 0]),
    ]:
        response = client.get(path, params=params)
        assert response.status_code == 200
        assert [row["value"] for row in response.json()] == expected


@pytest.mark.parametrize(
    "params",
    [
        {"recorded_from": "2026-11-24T10:00:00"},
        {"recorded_to": "not-a-time"},
        {"recorded_from": "2026-11-24T11:00:00Z", "recorded_to": "2026-11-24T10:00:00Z"},
        {"recorded_from": "0001-01-01T00:00:00+01:00"},
    ],
)
def test_reading_time_filters_reject_invalid_bounds(client, params):
    assert client.get("/api/v1/readings", params=params).status_code == 422
