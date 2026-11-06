import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from paho.mqtt.reasoncodes import ReasonCode
from paho.mqtt.packettypes import PacketTypes

from WebApp import WebApp
from MqttManager import MqttManager
from main import environment_port


def measurement(**overrides):
    return {"ir": 84231, "bpm": 72.4, "avg_bpm": 71,
            "finger_detected": True, "temperature_c": 36.2,
            "temperature_valid": True, "mpu_valid": True,
            "accel_batch": [[0.0, 0.0, 1.0, 1.0]] * 50,
            "fall_verdict": "no fall", "min_g_dip": 1.0, **overrides}


@pytest.fixture
def app(tmp_path):
    return WebApp(log_path=tmp_path / "history.txt")


def test_measurements_sse_history_and_download(app):
    client = app.app.test_client()
    assert client.get("/api/logs").json == []
    assert client.get("/download-logs").status_code == 404
    app.set_mqtt_connected(True)
    app.update_telemetry(measurement())
    stream = client.get("/chart-data", buffered=False)
    try:
        data = json.loads(next(stream.response).decode().removeprefix("data: "))
        assert (data["bpm"], data["sample_id"], len(data["accel_batch"])) == (72.4, 1, 50)
        assert data["mqtt_connected"] and not data["data_stale"]
    finally:
        stream.close()
    records = client.get("/api/logs").json
    assert json.loads(records[0]["raw"])["bpm"] == 72.4
    assert client.get("/download-logs").data == app.log_path.read_bytes()


@pytest.mark.parametrize("changes", [
    {"bpm": float("nan")}, {"bpm": 10 ** 1000}, {"bpm": True},
    {"finger_detected": "false"}, {"mpu_valid": 1},
    {"temperature_valid": False, "temperature_c": 36},
    {"accel_batch": [[1, 2]]}, {"accel_batch": [[0, 0, float("inf"), 1]]},
    {"accel_batch": [[0, 0, 1, 1]] * 51}, {"min_g_dip": "low"},
    {"ir": 0.5}, {"fall_verdict": "unknown"}, {"fall_canceled": "true"},
])
def test_invalid_payload_never_mutates_state_or_log(app, changes):
    app.update_telemetry(measurement())
    before = app.telemetry_snapshot()
    history = app.log_path.read_bytes()
    with pytest.raises((TypeError, ValueError)):
        app.update_telemetry(measurement(**changes))
    assert app.telemetry_snapshot() == before
    assert app.log_path.read_bytes() == history


def test_no_mpu_or_invalid_temperature_still_updates(app):
    app.update_telemetry(measurement(mpu_valid=False, accel_batch=[],
                                     temperature_valid=False, temperature_c=None))
    assert app.telemetry_snapshot()["sample_id"] == 1
    assert app.telemetry_snapshot()["temperature_c"] is None


def test_fall_timeout_at_zero_clock_and_cancel_are_logged(app):
    with patch("WebApp.time.monotonic", return_value=0):
        app.update_telemetry(measurement(fall_verdict="fall", min_g_dip=0.2))
    assert json.loads(app.log_path.read_text().splitlines()[-1])["fall_state"] == "WAITING_CONFIRMATION"
    with patch("WebApp.time.monotonic", return_value=10):
        snapshot = app.telemetry_snapshot()
        assert snapshot["fall_state"] == "FULL_ALERT" and snapshot["data_stale"]
        app.update_telemetry({"fall_canceled": True})
        snapshot = app.telemetry_snapshot()
        assert snapshot["fall_state"] == "NORMAL" and snapshot["data_stale"]
    events = [json.loads(line)["event"] for line in app.log_path.read_text().splitlines()]
    assert events == ["measurement", "fall_timeout", "fall_canceled"]


def test_history_failure_does_not_break_live_updates(app):
    app.log_path = app.log_path.parent / "missing" / "history.txt"
    app.update_telemetry(measurement())
    assert app.telemetry_snapshot()["bpm"] == 72.4
    assert app.telemetry_snapshot()["log_error"]


def test_history_returns_last_200_lines_and_preserves_legacy_text(app):
    app.log_path.write_text("".join(f"legacy {i}\n" for i in range(250)))
    rows = app.app.test_client().get("/api/logs").json
    assert len(rows) == 200
    assert rows[0]["raw"] == "legacy 249" and rows[-1]["raw"] == "legacy 50"


def test_subscription_requires_successful_suback(app):
    manager = MqttManager("localhost", 1883, "test", app.update_telemetry, app.set_mqtt_connected)
    client = Mock()
    client.subscribe.return_value = (0, 1)
    manager.client.on_connect(client, None, {}, 0)
    assert not app.telemetry_snapshot()["mqtt_connected"]
    manager.client.on_subscribe(client, None, 1, [ReasonCode(PacketTypes.SUBACK, identifier=0)])
    assert app.telemetry_snapshot()["mqtt_connected"]
    manager.client.on_subscribe(client, None, 1, [ReasonCode(PacketTypes.SUBACK, identifier=128)])
    assert not app.telemetry_snapshot()["mqtt_connected"]


def test_bad_or_retained_mqtt_does_not_stop_next_valid_message(app):
    manager = MqttManager("localhost", 1883, "test", app.update_telemetry)
    for payload, retain in [(b"not json", False), (b"[]", False), (b"\xff", False),
                            (b"x" * 16385, False), (b'{"fall_canceled":true}', True),
                            (json.dumps(measurement(bpm="bad")).encode(), False)]:
        manager.client.on_message(None, None, SimpleNamespace(topic="test", payload=payload, retain=retain))
    assert app.telemetry_snapshot()["sample_id"] == 0
    manager.client.on_message(None, None, SimpleNamespace(
        topic="test", payload=json.dumps(measurement()).encode(), retain=False))
    assert app.telemetry_snapshot()["sample_id"] == 1


def test_ports_are_validated(monkeypatch):
    for value in ("0", "65536", "invalid"):
        monkeypatch.setenv("WEB_PORT", value)
        with pytest.raises(ValueError):
            environment_port("WEB_PORT", 5000)
