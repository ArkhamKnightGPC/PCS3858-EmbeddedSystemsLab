from __future__ import annotations

import json
import logging
import math
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from flask import Flask, Response, render_template, stream_with_context, jsonify, send_file

logger = logging.getLogger(__name__)


class WebApp:
    """Flask dashboard backed by batched MQTT telemetry and Fall Alert confirmation."""

    STALE_AFTER_SECONDS = 5
    CONFIRMATION_TIMEOUT_SECONDS = 10  # Waiting state timeout window

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5000,
        debug: bool = False,
        mqtt_topic: str = "wearable/finger/measurements",
        log_path: str | Path | None = None,
    ):
        self.app = Flask(__name__)
        self.host = host
        self.port = port
        self.debug = debug
        self.mqtt_topic = mqtt_topic
        self.log_path = Path(log_path or Path(__file__).with_name("telemetry_history.txt")).resolve()
        self._lock = threading.Lock()
        self._mqtt_connected = False
        self._last_received_monotonic: float | None = None
        self._waiting_since_monotonic: float | None = None

        self._telemetry: dict[str, Any] = {
            "ir": None,
            "bpm": None,
            "avg_bpm": None,
            "finger_detected": False,
            "temperature_c": None,
            "temperature_valid": False,
            "accel_batch": [],
            "fall_state": "NORMAL",  # Modes: "NORMAL", "WAITING_CONFIRMATION", "FULL_ALERT"
            "min_g_dip": 1.0,
            "mpu_valid": False,
            "last_update": None,
            "sample_id": 0,
            "heart_rate_valid": False,
            "log_error": False,
        }

        self.app.add_url_rule("/", "index", self.index)
        self.app.add_url_rule("/chart-data", "chart_data", self.chart_data)

        self.app.add_url_rule("/api/logs", "get_logs", self.get_logs)
        self.app.add_url_rule("/download-logs", "download_logs", self.download_logs)

    def get_logs(self) -> Response:
        """Returns parsed log history from the txt file as JSON."""
        # Bound reads even after months of telemetry; preserve legacy text lines.
        try:
            with self._lock, self.log_path.open("rb") as history:
                size = history.seek(0, 2)
                start = max(0, size - 2 * 1024 * 1024)
                history.seek(start)
                if start:
                    history.readline()
                lines = history.read().decode("utf-8", errors="replace").splitlines()
            return jsonify([{"raw": line} for line in reversed(lines[-200:])])
        except FileNotFoundError:
            return jsonify([])
        except OSError:
            logger.exception("Cannot read telemetry history")
            return jsonify({"error": "Cannot read telemetry history"}), 503

    def download_logs(self) -> Response:
        """Allows downloading the raw .txt file."""
        if self.log_path.is_file():
            return send_file(self.log_path, as_attachment=True, download_name="wearable_telemetry_history.txt")
        return Response("Log file not found", status=404)

    @staticmethod
    def _number(payload: dict[str, Any], field: str) -> float:
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{field} must be a number")
        if abs(value) > 1e12 or not math.isfinite(value):
            raise ValueError(f"{field} must be finite")
        return float(value)

    @staticmethod
    def _boolean(payload: dict[str, Any], field: str, default=None) -> bool:
        value = payload.get(field, default)
        if not isinstance(value, bool):
            raise TypeError(f"{field} must be a boolean")
        return value

    def _record_locked(self, event: str) -> None:
        record = {**self._telemetry, "event": event,
                  "received_at": datetime.now().astimezone().isoformat()}
        try:
            with self.log_path.open("a", encoding="utf-8") as history:
                history.write(json.dumps(record, allow_nan=False) + "\n")
            self._telemetry["log_error"] = False
        except OSError:
            self._telemetry["log_error"] = True
            logger.exception("Cannot append telemetry history; live telemetry continues")

    def _advance_fall_state_locked(self) -> None:
        if (self._telemetry["fall_state"] == "WAITING_CONFIRMATION"
                and self._waiting_since_monotonic is not None
                and time.monotonic() - self._waiting_since_monotonic >= self.CONFIRMATION_TIMEOUT_SECONDS):
            self._telemetry["fall_state"] = "FULL_ALERT"
            self._waiting_since_monotonic = None
            self._record_locked("fall_timeout")

    def update_telemetry(self, payload: dict[str, Any]) -> None:
        """Process wearable telemetry and manage fall state machine."""
        canceled = self._boolean(payload, "fall_canceled", False)
        if canceled:
            with self._lock:
                self._telemetry["fall_state"] = "NORMAL"
                self._waiting_since_monotonic = None
                self._record_locked("fall_canceled")
            return

        # Validate the entire message before changing state or appending history.
        ir = self._number(payload, "ir")
        bpm = self._number(payload, "bpm")
        avg_bpm = self._number(payload, "avg_bpm")
        if ir < 0 or not ir.is_integer() or bpm < 0 or avg_bpm < 0 or not avg_bpm.is_integer():
            raise ValueError("Invalid IR/BPM values")
        finger_detected = self._boolean(payload, "finger_detected")
        temperature_valid = self._boolean(payload, "temperature_valid")
        mpu_valid = self._boolean(payload, "mpu_valid", False)
        heart_rate_valid = self._boolean(payload, "heart_rate_valid", finger_detected and bpm > 0)
        temperature = self._number(payload, "temperature_c") if temperature_valid else None
        if not temperature_valid and payload.get("temperature_c") is not None:
            raise ValueError("Invalid temperature must be null")
        accel_batch = payload.get("accel_batch", [])
        if not isinstance(accel_batch, list) or len(accel_batch) > 50:
            raise ValueError("accel_batch must contain at most 50 samples")
        checked_batch = []
        for sample in accel_batch:
            if not isinstance(sample, list) or len(sample) != 4:
                raise ValueError("Acceleration samples must contain x, y, z and magnitude")
            checked_batch.append([self._number({"axis": value}, "axis") for value in sample])
        if not mpu_valid and checked_batch:
            raise ValueError("Invalid MPU must have an empty batch")
        fall_verdict = payload.get("fall_verdict", "no fall")
        if fall_verdict not in ("fall", "no fall") or (fall_verdict == "fall" and not mpu_valid):
            raise ValueError("Invalid fall verdict")
        min_g_dip = self._number({"min_g_dip": payload.get("min_g_dip", 1.0)}, "min_g_dip")

        with self._lock:
            self._advance_fall_state_locked()
            current_state = self._telemetry["fall_state"]

            if fall_verdict == "fall" and current_state == "NORMAL":
                # Requirement 3: Enter waiting state
                self._telemetry["fall_state"] = "WAITING_CONFIRMATION"
                self._waiting_since_monotonic = time.monotonic()

            self._telemetry.update({
                "ir": int(ir),
                "bpm": round(bpm, 1),
                "avg_bpm": int(avg_bpm),
                "finger_detected": finger_detected,
                "temperature_c": round(temperature, 1) if temperature is not None else None,
                "temperature_valid": temperature_valid,
                "accel_batch": checked_batch,
                "min_g_dip": min_g_dip,
                "mpu_valid": mpu_valid,
                "last_update": datetime.now().astimezone().strftime("%H:%M:%S"),
                "sample_id": self._telemetry["sample_id"] + 1,
                "heart_rate_valid": heart_rate_valid,
            })
            self._last_received_monotonic = time.monotonic()
            self._record_locked("measurement")

    def set_mqtt_connected(self, connected: bool) -> None:
        with self._lock:
            self._mqtt_connected = connected

    def telemetry_snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._advance_fall_state_locked()
            snapshot = dict(self._telemetry)
            mqtt_connected = self._mqtt_connected
            last_received = self._last_received_monotonic

        snapshot["mqtt_connected"] = mqtt_connected
        snapshot["data_stale"] = (
            last_received is None
            or time.monotonic() - last_received > self.STALE_AFTER_SECONDS
        )
        return snapshot

    def index(self) -> str:
        return render_template("index.html", mqtt_topic=self.mqtt_topic)

    def update_data(self) -> Iterator[str]:
        while True:
            snapshot = self.telemetry_snapshot()
            yield f"data: {json.dumps(snapshot)}\n\n"
            time.sleep(0.5)

    def chart_data(self) -> Response:
        response = Response(
            stream_with_context(self.update_data()),
            mimetype="text/event-stream",
        )
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        return response

    def run(self) -> None:
        self.app.run(
            host=self.host,
            port=self.port,
            debug=self.debug,
            use_reloader=False,
            threaded=True,
        )
