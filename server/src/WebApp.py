from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime
from typing import Any, Iterator

from flask import Flask, Response, render_template, stream_with_context


class WebApp:
    """Flask dashboard backed by the latest MQTT telemetry sample."""

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
            "accel": None,
            "gyro": None,
            "accel_magnitude": 0.0,
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

    def _vector3(self, payload: dict[str, Any], field: str) -> dict[str, float] | None:
        obj = payload.get(field)
        if obj is None:
            return None
        if not isinstance(obj, dict):
            raise TypeError(f"{field} must be a dictionary")

        return {
            "x": round(self._number(obj, "x"), 2),
            "y": round(self._number(obj, "y"), 2),
            "z": round(self._number(obj, "z"), 2),
        }

    def update_telemetry(self, payload: dict[str, Any]) -> None:
        """Validate and atomically store one wearable MQTT message."""
        ir = self._number(payload, "ir")
        bpm = self._number(payload, "bpm")
        avg_bpm = self._number(payload, "avg_bpm")

        finger_detected = payload.get("finger_detected")
        temperature_valid = payload.get("temperature_valid")
        mpu_valid = payload.get("mpu_valid", False)

        if not isinstance(finger_detected, bool):
            raise TypeError("finger_detected must be a boolean")
        if not isinstance(temperature_valid, bool):
            raise TypeError("temperature_valid must be a boolean")
        if not isinstance(mpu_valid, bool):
            raise TypeError("mpu_valid must be a boolean")

        temperature = payload.get("temperature_c")
        if temperature_valid:
            temperature = self._number(payload, "temperature_c")
        elif temperature is not None:
            raise ValueError("temperature_c must be null when it is invalid")

        accel = self._vector3(payload, "accel") if mpu_valid else None
        gyro = self._vector3(payload, "gyro") if mpu_valid else None

        accel_magnitude = 0.0
        if accel:
            accel_magnitude = round(
                math.sqrt(accel["x"]**2 + accel["y"]**2 + accel["z"]**2), 2
            )

        sample = {
            "ir": int(ir),
            "bpm": round(bpm, 1),
            "avg_bpm": int(avg_bpm),
            "finger_detected": finger_detected,
            "temperature_c": round(temperature, 1) if temperature is not None else None,
            "temperature_valid": temperature_valid,
            "accel": accel,
            "gyro": gyro,
            "accel_magnitude": accel_magnitude,
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

            # Dispara SSE apenas quando houver novos dados ou mudança de estado de conexão
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