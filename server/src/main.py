import os
import threading
import time

from MqttManager import MqttManager
from WebApp import WebApp


def environment_port(name: str, default: int) -> int:
    value = os.getenv(name, str(default))
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer, got {value!r}") from error


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
        on_message=web_app.update_telemetry,
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
