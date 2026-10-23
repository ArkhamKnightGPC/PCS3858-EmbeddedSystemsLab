from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime
from typing import Any, Iterator

from flask import Flask, Response, render_template, stream_with_context


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
    ):
        self.app = Flask(__name__)
        self host = host
        self.port = port
        self.debug = debug
        self.mqtt_topic = mqtt_topic
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
        }

        self.app.add_url_rule("/", "index", self.index)
        self.app.add_url_rule("/chart-data", "chart_data", self.chart_data)

    @staticmethod
    def _number(payload: dict[str, Any], field: str) -> float:
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{field} must be a number")
        if not math.isfinite(value):
            raise ValueError(f"{field} must be finite")
        return float(value)

    def update_telemetry(self, payload: dict[str, Any]) -> None:
        """Process wearable telemetry and manage fall state machine."""
        with self._lock:
            # Requirement 4: Handle cancellation message from button press
            if payload.get("fall_canceled") is True:
                self._telemetry["fall_state"] = "NORMAL"
                self._waiting_since_monotonic = None
                return

            ir = self._number(payload, "ir")
            bpm = self._number(payload, "bpm")
            avg_bpm = self._number(payload, "avg_bpm")

            finger_detected = payload.get("finger_detected")
            temperature_valid = payload.get("temperature_valid")
            mpu_valid = payload.get("mpu_valid", False)

            temperature = payload.get("temperature_c")
            if temperature_valid:
                temperature = self._number(payload, "temperature_c")

            accel_batch = payload.get("accel_batch", [])
            fall_verdict = payload.get("fall_verdict", "no fall")
            min_g_dip = payload.get("min_g_dip", 1.0)

            # State Machine Evaluation
            current_state = self._telemetry["fall_state"]

            if fall_verdict == "fall" and current_state == "NORMAL":
                # Requirement 3: Enter waiting state
                self._telemetry["fall_state"] = "WAITING_CONFIRMATION"
                self._waiting_since_monotonic = time.monotonic()

            elif current_state == "WAITING_CONFIRMATION" and self._waiting_since_monotonic:
                elapsed = time.monotonic() - self._waiting_since_monotonic
                if elapsed > self.CONFIRMATION_TIMEOUT_SECONDS:
                    # Requirement 4: Timeout reached -> Trigger FULL BLOWN ALERT
                    self._telemetry["fall_state"] = "FULL_ALERT"

            self._telemetry.update({
                "ir": int(ir),
                "bpm": round(bpm, 1),
                "avg_bpm": int(avg_bpm),
                "finger_detected": finger_detected,
                "temperature_c": round(temperature, 1) if temperature is not None else None,
                "temperature_valid": temperature_valid,
                "accel_batch": accel_batch,
                "min_g_dip": min_g_dip,
                "mpu_valid": mpu_valid,
                "last_update": datetime.now().astimezone().strftime("%H:%M:%S"),
            })
            self._last_received_monotonic = time.monotonic()

    def set_mqtt_connected(self, connected: bool) -> None:
        with self._lock:
            self._mqtt_connected = connected

    def telemetry_snapshot(self) -> dict[str, Any]:
        with self._lock:
            snapshot = dict(self._telemetry)
            mqtt_connected = self._mqtt_connected
            last_received = self._last_received_monotonic

            # Check timeout during idle streaming
            if (
                snapshot["fall_state"] == "WAITING_CONFIRMATION"
                and self._waiting_since_monotonic
                and (time.monotonic() - self._waiting_since_monotonic > self.CONFIRMATION_TIMEOUT_SECONDS)
            ):
                snapshot["fall_state"] = "FULL_ALERT"
                self._telemetry["fall_state"] = "FULL_ALERT"

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