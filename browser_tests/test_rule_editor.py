"""Browser checks against an isolated, API-key-protected service."""

import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import create_engine, update

from sensorwatch.models import SensorReading


@pytest.fixture
def dashboard(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "SENSORWATCH_DATABASE_URL": f"sqlite:///{tmp_path / 'browser.db'}",
        "SENSORWATCH_INGEST_API_KEY": "browser-test-key",
    }
    subprocess.run([sys.executable, "-m", "sensorwatch", "migrate"], env=env, check=True)
    with (tmp_path / "server.log").open("w") as log:
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "sensorwatch.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            with httpx.Client(base_url=url, headers={"X-API-Key": "browser-test-key"}) as api:
                for _ in range(100):
                    try:
                        if api.get("/health").status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    if server.poll() is not None:
                        pytest.fail("Browser test server exited before startup")
                    time.sleep(0.1)
                else:
                    pytest.fail("Browser test server did not become healthy")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    page = browser.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    yield page, api, url
                    assert errors == []
                    browser.close()
        finally:
            server.terminate()
            server.wait(timeout=10)


def seed(api, sensor="boiler-01"):
    assert (
        api.post(
            "/api/v1/readings",
            json={
                "sensor_id": sensor,
                "metric": "temperature",
                "value": 20,
            },
        ).status_code
        == 201
    )


def test_create_edit_delete_and_apply_rule(dashboard):
    page, api, url = dashboard
    seed(api)
    page.goto(url)
    expect(page.locator("#rule-status")).to_have_text(
        "No custom rule. Global detection settings apply."
    )
    page.get_by_label("Upper bound").fill("80")
    page.get_by_role("button", name="Save rule").click()
    expect(page.locator("#rule-status")).to_contain_text("API key")
    expect(page.get_by_label("Upper bound")).to_have_value("80")
    page.get_by_label("API key", exact=True).fill("browser-test-key")
    page.get_by_role("button", name="Save rule").click()
    expect(page.locator("#rule-status")).to_have_text("Rule saved.")
    reading = api.post(
        "/api/v1/readings",
        json={
            "sensor_id": "boiler-01",
            "metric": "temperature",
            "value": 81,
        },
    ).json()
    assert reading["is_anomaly"] is True
    assert reading["applied_rule"]["upper_bound"] == 80
    page.get_by_label("Upper bound").fill("90")
    page.get_by_label("Detection threshold").fill("5")
    page.get_by_role("button", name="Save rule").click()
    expect(page.locator("#rule-status")).to_have_text("Rule saved.")
    assert api.get("/api/v1/rules/boiler-01/temperature").json()["upper_bound"] == 90
    page.reload()
    expect(page.get_by_label("Upper bound")).to_have_value("90")
    expect(page.get_by_label("API key", exact=True)).to_be_empty()
    page.get_by_label("API key", exact=True).fill("browser-test-key")
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Delete rule").click()
    expect(page.locator("#rule-status")).to_have_text(
        "Rule deleted. Global detection settings apply."
    )
    assert api.get("/api/v1/rules/boiler-01/temperature").status_code == 404


def test_validation_selection_and_responsive_layout(dashboard):
    page, api, url = dashboard
    page.goto(url)
    expect(page.get_by_role("button", name="Save rule")).to_be_disabled()
    seed(api)
    seed(api, "boiler-02")
    page.reload()
    expect(page.get_by_label("Upper bound")).to_be_enabled()
    page.get_by_label("Lower bound").fill("90")
    page.get_by_label("Upper bound").fill("80")
    page.get_by_role("button", name="Save rule").click()
    expect(page.locator("#rule-status")).to_contain_text("less than")
    assert api.get("/api/v1/rules").json() == []
    page.get_by_label("Sensor series").select_option(label="boiler-02 · temperature")
    expect(page.locator("#rule-series")).to_have_text("boiler-02 / temperature")
    expect(page.get_by_label("Upper bound")).to_be_empty()
    for width in (320, 768, 1024, 1440):
        page.set_viewport_size({"width": width, "height": 900})
        panel = page.locator("#rule-editor").bounding_box()
        assert panel["x"] >= 0
        assert panel["x"] + panel["width"] <= width
        if width in (320, 1440):
            page.keyboard.press("Control+Home")
            output = Path("build/browser-check")
            output.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(output / f"dashboard-{width}.png"), full_page=True)


def test_refresh_preserves_draft_and_reload_discards_it(dashboard):
    page, api, url = dashboard
    seed(api)
    page.clock.install()
    page.goto(url)
    expect(page.get_by_label("Upper bound")).to_be_enabled()
    page.get_by_label("Upper bound").fill("75")
    with page.expect_response("**/api/v1/summary"):
        page.clock.fast_forward(10000)
    expect(page.get_by_label("Upper bound")).to_have_value("75")
    page.get_by_role("button", name="Reload rule").click()
    expect(page.get_by_label("Upper bound")).to_be_empty()


def test_load_failure_can_be_retried(dashboard):
    page, api, url = dashboard
    seed(api)
    pattern = "**/api/v1/rules/boiler-01/temperature"
    page.route(
        pattern,
        lambda route: route.fulfill(
            status=503, content_type="application/json", body='{"detail":"Rules unavailable"}'
        ),
    )
    page.goto(url)
    expect(page.locator("#rule-status")).to_have_text("Rules unavailable")
    expect(page.get_by_role("button", name="Save rule")).to_be_disabled()
    page.unroute(pattern)
    page.get_by_role("button", name="Reload rule").click()
    expect(page.get_by_role("button", name="Save rule")).to_be_enabled()


def test_delete_cancellation_and_clear_key(dashboard):
    page, api, url = dashboard
    seed(api)
    path = "/api/v1/rules/boiler-01/temperature"
    assert api.put(path, json={"upper_bound": 80}).status_code == 200
    page.goto(url)
    expect(page.get_by_label("Upper bound")).to_have_value("80")
    page.get_by_label("API key", exact=True).fill("browser-test-key")
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.get_by_role("button", name="Delete rule").click()
    assert api.get(path).status_code == 200
    page.get_by_role("button", name="Clear key").click()
    expect(page.get_by_label("API key", exact=True)).to_be_empty()
    page.get_by_role("button", name="Save rule").click()
    expect(page.locator("#rule-status")).to_contain_text("API key")


def test_stream_status_timeout_and_recovery(dashboard, tmp_path):
    page, api, url = dashboard
    seed(api)
    page.clock.install()
    page.goto(url)
    expect(page.locator(".stream-status")).to_have_text("Online")
    page.get_by_label("API key", exact=True).fill("browser-test-key")
    page.get_by_label("Stale after (seconds)").fill("60")
    page.get_by_role("button", name="Save rule").click()
    expect(page.locator("#rule-status")).to_have_text("Rule saved.")
    assert api.get("/api/v1/rules/boiler-01/temperature").json()["stale_after_seconds"] == 60
    engine = create_engine(f"sqlite:///{tmp_path / 'browser.db'}")
    with engine.begin() as connection:
        connection.execute(
            update(SensorReading).values(
                created_at=datetime.now(timezone.utc) - timedelta(seconds=61)
            )
        )
    engine.dispose()
    with page.expect_response("**/api/v1/sensors"):
        page.clock.fast_forward(10000)
    expect(page.locator(".stream-status")).to_have_text("Stale")
    expect(page.locator("#stale-series-count")).to_have_text("1 stale streams")
    expect(page.locator(".stream-meta")).to_contain_text("Last received")
    seed(api)
    with page.expect_response("**/api/v1/sensors"):
        page.clock.fast_forward(10000)
    expect(page.locator(".stream-status")).to_have_text("Online")
    expect(page.locator("#stale-series-count")).to_have_text("0 stale streams")
    page.reload()
    expect(page.get_by_label("Stale after (seconds)")).to_have_value("60")
