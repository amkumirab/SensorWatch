from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from sensorwatch.api import app
from sensorwatch.db import get_db
from sensorwatch.models import SensorReading

PATH = "/api/v1/readings"
EVENT = {"sensor_id": "pump", "metric": "pressure", "value": 12, "event_id": "boot1:42"}


def test_retry_returns_original_decision_after_rule_change(client):
    rule = "/api/v1/rules/pump/pressure"
    client.put(rule, json={"upper_bound": 10})
    first = client.post(PATH, json=EVENT)
    assert first.status_code == 201
    client.put(rule, json={"upper_bound": 20})
    retry = client.post(PATH, json=EVENT)
    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert retry.json()["event_id"] == EVENT["event_id"]
    assert len(client.get(PATH).json()) == 1
    assert len(client.get("/api/v1/alerts").json()) == 1


@pytest.mark.parametrize(
    "change", [{"value": 13}, {"unit": "bar"}, {"recorded_at": "2026-11-18T12:00:00Z"}]
)
def test_changed_event_conflicts_without_side_effects(client, change):
    original = client.post(PATH, json=EVENT).json()
    response = client.post(PATH, json=EVENT | change)
    assert response.status_code == 409
    assert client.get(PATH).json() == [original]


def test_key_is_scoped_to_sensor_and_metric_and_optional(client):
    for payload in [EVENT, EVENT | {"sensor_id": "other"}, EVENT | {"metric": "temperature"}]:
        assert client.post(PATH, json=payload).status_code == 201
    for _ in range(2):
        assert client.post(PATH, json=EVENT | {"event_id": None}).status_code == 201
    assert len(client.get(PATH).json()) == 5


@pytest.mark.parametrize("event_id", ["", "x" * 129, "bad id", "a/b", "\u062a\u0633\u062a"])
def test_event_id_validation(client, event_id):
    assert client.post(PATH, json=EVENT | {"event_id": event_id}).status_code == 422


def test_timestamp_and_numeric_normalization(client):
    payload = EVENT | {"value": -0.0, "recorded_at": "2026-11-18T14:00:00+02:00"}
    first = client.post(PATH, json=payload)
    retry = client.post(
        PATH, json=payload | {"value": 0, "unit": "", "recorded_at": "2026-11-18T12:00:00Z"}
    )
    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert (
        client.post(PATH, json=payload | {"recorded_at": "2026-11-18T12:00:00"}).status_code
        == 200
    )
    assert (
        client.post(PATH, json=payload | {"recorded_at": "2026-11-18T12:00:01Z"}).status_code
        == 409
    )


def test_batch_preserves_order_and_counts_replays(client):
    original = client.post(PATH, json=EVENT).json()
    second = EVENT | {"event_id": "boot1:43", "value": 13}
    payload = {"readings": [EVENT, second, second]}
    response = client.post(PATH + "/batch", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert (body["accepted"], body["created"], body["replayed"]) == (3, 1, 2)
    assert body["readings"][0] == original
    assert body["readings"][1] == body["readings"][2]
    retry = client.post(PATH + "/batch", json=payload)
    assert retry.status_code == 200
    assert (retry.json()["created"], retry.json()["replayed"]) == (0, 3)
    assert len(client.get(PATH).json()) == 2


@pytest.mark.parametrize("existing", [False, True])
def test_batch_conflict_rolls_back_every_new_reading_and_alert(client, existing):
    client.put("/api/v1/rules/pump/pressure", json={"upper_bound": 10})
    if existing:
        client.post(PATH, json=EVENT)
    before = client.get(PATH).json()
    alerts = client.get("/api/v1/alerts").json()
    response = client.post(
        PATH + "/batch",
        json={
            "readings": [
                EVENT | {"event_id": None},
                EVENT | {"event_id": "new"},
                EVENT,
                EVENT | {"value": 15},
            ]
        },
    )
    assert response.status_code == 409
    assert client.get(PATH).json() == before
    assert client.get("/api/v1/alerts").json() == alerts


def test_retry_does_not_refresh_receipt_time(client):
    client.post(PATH, json=EVENT)
    dependency = app.dependency_overrides[get_db]()
    db = next(dependency)
    try:
        row = db.scalar(select(SensorReading))
        row.created_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
    finally:
        dependency.close()
    assert client.post(PATH, json=EVENT).status_code == 200
    assert client.get("/api/v1/sensors").json()[0]["connectivity_status"] == "stale"


def test_concurrent_retries_create_one_reading_and_alert(client):
    client.put("/api/v1/rules/pump/pressure", json={"upper_bound": 10})
    with ThreadPoolExecutor(max_workers=6) as workers:
        results = list(workers.map(lambda _: client.post(PATH, json=EVENT), range(12)))
    assert sorted(result.status_code for result in results) == [200] * 11 + [201]
    assert len({result.json()["id"] for result in results}) == 1
    assert len(client.get(PATH).json()) == 1
    assert len(client.get("/api/v1/alerts").json()) == 1


def test_concurrent_conflicting_payloads_do_not_overwrite_winner(client):
    payloads = [EVENT, EVENT | {"value": 99}]
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda payload: client.post(PATH, json=payload), payloads))
    assert sorted(result.status_code for result in results) == [201, 409]
    winner = next(result.json() for result in results if result.status_code == 201)
    assert client.get(PATH).json() == [winner]


def test_keyed_readings_use_the_same_baseline_as_ordinary_readings(client):
    for index, value in enumerate([20, 20.1, 19.9, 20.05, 19.95, 20] * 3 + [32, 20]):
        keyed = EVENT | {"event_id": f"event-{index}", "value": value}
        ordinary = keyed | {"sensor_id": "ordinary", "event_id": None}
        expected = client.post(PATH, json=ordinary).json()
        first = client.post(PATH, json=keyed).json()
        assert client.post(PATH, json=keyed).json() == first
        for field in (
            "anomaly_score",
            "is_anomaly",
            "detector_status",
            "baseline_center",
            "baseline_scale",
        ):
            assert first[field] == expected[field]
    assert len(client.get("/api/v1/alerts").json()) == 2
