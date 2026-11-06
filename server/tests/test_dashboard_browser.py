import os
import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

from WebApp import WebApp
from test_telemetry import measurement


@pytest.fixture
def live_app(tmp_path):
    app = WebApp(log_path=tmp_path / "history.txt")
    app.set_mqtt_connected(True)
    app.update_telemetry(measurement())
    server = make_server("127.0.0.1", 0, app.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield app, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join(timeout=3)
    server.server_close()


@pytest.fixture
def browser():
    with sync_playwright() as playwright:
        executable = os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        browser = playwright.chromium.launch(executable_path=executable, headless=True)
        yield browser
        browser.close()


def test_tabs_history_refresh_download_without_chart_cdn(live_app, browser, tmp_path):
    app, url = live_app
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route("**/chart.umd.min.js", lambda route: route.abort())
    page.goto(url)
    expect(page.locator("#bpm-val")).to_have_text("72.4")
    expect(page.locator("#chart-status")).to_be_visible()
    page.get_by_role("button", name="Logs & History").click()
    expect(page.locator("#logs-tab")).to_be_visible()
    expect(page.locator("#realtime-tab")).not_to_be_visible()
    expect(page.locator("#log-table-body")).to_contain_text('"bpm": 72.4')
    with app.log_path.open("a") as history:
        history.write('<img src=x onerror="window.injected=true">\n')
    page.locator("#refresh-logs").click()
    expect(page.locator("#log-table-body")).to_contain_text("<img")
    assert page.locator("#log-table-body img").count() == 0
    assert not page.evaluate("Boolean(window.injected)")
    with page.expect_download() as download_info:
        page.get_by_role("link", name="Download .txt File").click()
    assert download_info.value.suggested_filename == "wearable_telemetry_history.txt"
    page.get_by_role("button", name="Real-Time Dashboard").click()
    expect(page.locator("#realtime-tab")).to_be_visible()
    app.set_mqtt_connected(False)
    expect(page.locator("#bpm-val")).to_have_text("--")
    expect(page.locator("#mpu-seismo-status")).to_have_text("IMU Inativa")
    assert not errors
    page.close()


def test_repeated_sse_does_not_duplicate_acceleration_batch(live_app, browser):
    app, url = live_app
    page = browser.new_page()
    # Deterministic Chart API double: actual DOM, EventSource, HTTP and JS execute
    # in Chromium. This test checks sample insertion, not Chart.js rendering.
    page.route("**/chart.umd.min.js", lambda route: route.fulfill(
        content_type="application/javascript", body="""
        window.charts = [];
        window.Chart = class {
            constructor(context, config) { this.data = config.data; window.charts.push(this); }
            update() {} resize() {}
        };
        """))
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(url)
    page.wait_for_function("window.charts?.[2]?.data.labels.length === 50")
    # Observe at least two heartbeat snapshots with the same sample_id.
    page.wait_for_timeout(1200)
    assert page.evaluate("window.charts[2].data.labels.length") == 50
    app.update_telemetry(measurement(bpm=80))
    page.wait_for_function("window.charts[2].data.labels.length === 100")
    expect(page.locator("#bpm-val")).to_have_text("80.0")
    with app._lock:
        app._last_received_monotonic -= 6
    expect(page.locator("#bpm-val")).to_have_text("--")
    expect(page.locator("#accel-x-val")).to_have_text("--")
    assert not errors
    page.close()
