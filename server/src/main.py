import os
import threading
import time
import json
from datetime import datetime

from MqttManager import MqttManager
from WebApp import WebApp

LOG_FILE_PATH = "telemetry_history.txt"

def log_telemetry_to_file(telemetry: dict):
    """Appends incoming valid telemetry records to a local text log file."""
    # Format a ISO timestamp or readable datetime line
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    bpm = telemetry.get("bpm", 0.0)
    avg_bpm = telemetry.get("avg_bpm", 0)
    temp = telemetry.get("temperature_c", "N/A") if telemetry.get("temperature_valid") else "N/A"
    finger = "YES" if telemetry.get("finger_detected") else "NO"
    fall_state = telemetry.get("fall_state", "NORMAL")

    log_entry = (
        f"[{timestamp}] BPM: {bpm:.1f} | Avg BPM: {avg_bpm} | "
        f"Temp: {temp}°C | Finger: {finger} | Status: {fall_state}\n"
    )

    with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
        f.write(log_entry)


def environment_port(name: str, default: int) -> int:
    value = os.getenv(name, str(default))
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer, got {value!r}") from error

def handle_mqtt_message(payload: dict):
    web_app.update_telemetry(payload)
    log_telemetry_to_file(payload)

if __name__ == "__main__":
    mqtt_topic = "wearable/finger/measurements"
    mqtt_username = "USER"
    mqtt_password = "PASS"
    if not mqtt_username or not mqtt_password:
        raise RuntimeError(
            "MQTT_USERNAME and MQTT_PASSWORD must be configured before startup"
        )

    web_app = WebApp(
        host=os.getenv("WEB_HOST", "10.49.29.243"),
        port=environment_port("WEB_PORT", 5000),
        debug=False,
        mqtt_topic=mqtt_topic,
    )

    mqtt_manager = MqttManager(
        broker=os.getenv("MQTT_BROKER", "10.49.29.243"),
        port=environment_port("MQTT_PORT", 1883),
        sub_topic=mqtt_topic,
        username=mqtt_username,
        password=mqtt_password,
        on_message=handle_mqtt_message,
        on_connection_change=web_app.set_mqtt_connected,
    )
    mqtt_manager.run_threaded()

    flask_thread = threading.Thread(target=web_app.run, daemon=True)
    flask_thread.start()

    print("\n--- Central Dashboard Server Running ---")
    print(f"Web Dashboard: http://localhost:{web_app.port}")
    print("Press Ctrl+C to exit.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        mqtt_manager.stop()
