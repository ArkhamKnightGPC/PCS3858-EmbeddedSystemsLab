from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime
from typing import Any, Iterator

from flask import Flask, Response, render_template, stream_with_context


class WebApp:
    """Flask dashboard backed by batched MQTT telemetry."""

    STALE_AFTER_SECONDS = 5

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5000,
        debug: bool = False,
        mqtt_topic: str = "wearable/finger/measurements",
    ):
        self.app = Flask(__name__)
        self.host = host
        self.port = port
        self.debug = debug
        self.mqtt_topic = mqtt_topic
        self._lock = threading.Lock()
        self._mqtt_connected = False
        self._last_received_monotonic: float | None = None
        self._telemetry: dict[str, Any] = {
            "ir": None,
            "bpm": None,
            "avg_bpm": None,
            "finger_detected": False,
            "temperature_c": None,
            "temperature_valid": False,
            "accel_batch": [],
            "accel_magnitude_batch": [],
            "min_g_dip": 1.0,
            "fall_detected": False,
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
        """Validate and atomically store one wearable MQTT message."""
        ir = self._number(payload, "ir")
        bpm = self._number(payload, "bpm")
        avg_bpm = self._number(payload, "avg_bpm")

        finger_detected = payload.get("finger_detected")
        temperature_valid = payload.get("temperature_valid")
        mpu_valid = payload.get("mpu_valid", False)

        if not isinstance(finger_detected, bool) or not isinstance(temperature_valid, bool):
            raise TypeError("Boolean validation failed")

        temperature = payload.get("temperature_c")
        if temperature_valid:
            temperature = self._number(payload, "temperature_c")

        # Unpack batched accelerometer samples [[ax, ay, az], ...]
        accel_batch = payload.get("accel_batch", [])
        magnitude_batch = []
        min_g_dip = 1.0
        fall_detected = False

        if mpu_valid and isinstance(accel_batch, list):
            for sample in accel_batch:
                if isinstance(sample, list) and len(sample) == 3:
                    ax, ay, az = sample[0], sample[1], sample[2]
                    mag = round(math.sqrt(ax**2 + ay**2 + az**2), 2)
                    magnitude_batch.append(mag)

            if magnitude_batch:
                min_g_dip = min(magnitude_batch)
                # Detection condition: Acceleration drops below 0.3g threshold
                if min_g_dip <= 0.3:
                    fall_detected = True

        sample = {
            "ir": int(ir),
            "bpm": round(bpm, 1),
            "avg_bpm": int(avg_bpm),
            "finger_detected": finger_detected,
            "temperature_c": round(temperature, 1) if temperature is not None else None,
            "temperature_valid": temperature_valid,
            "accel_batch": accel_batch,
            "accel_magnitude_batch": magnitude_batch,
            "min_g_dip": min_g_dip,
            "fall_detected": fall_detected,
            "mpu_valid": mpu_valid,
            "last_update": datetime.now().astimezone().strftime("%H:%M:%S"),
        }

        with self._lock:
            self._telemetry = sample
            self._last_received_monotonic = time.monotonic()

    def set_mqtt_connected(self, connected: bool) -> None:
        with self._lock:
            self._mqtt_connected = connected

    def telemetry_snapshot(self) -> dict[str, Any]:
        with self._lock:
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
        last_sent_update = None
        while True:
            snapshot = self.telemetry_snapshot()
            current_update = snapshot.get("last_update")

            if current_update != last_sent_update or snapshot.get("data_stale"):
                last_sent_update = current_update
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