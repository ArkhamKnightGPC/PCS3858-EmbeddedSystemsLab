import os
from pathlib import Path

from dotenv import load_dotenv

from MqttManager import MqttManager
from WebApp import WebApp

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def load_environment() -> None:
    # Keep exported/service variables authoritative and passwords literal.
    load_dotenv(ENV_FILE, override=False, interpolate=False)


def environment_port(name: str, default: int) -> int:
    value = os.getenv(name, str(default))
    try:
        port = int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer, got {value!r}") from error
    if not 1 <= port <= 65535:
        raise ValueError(f"{name} must be between 1 and 65535")
    return port

def main():
    load_environment()
    mqtt_topic = os.getenv("MQTT_TOPIC", "wearable/finger/measurements")
    mqtt_username = os.getenv("MQTT_USERNAME")
    mqtt_password = os.getenv("MQTT_PASSWORD")
    if not mqtt_username or not mqtt_password:
        raise RuntimeError(
            "Configure MQTT_USERNAME and MQTT_PASSWORD in server/.env or the environment before startup"
        )

    web_app = WebApp(
        host=os.getenv("WEB_HOST", "0.0.0.0"),
        port=environment_port("WEB_PORT", 5000),
        debug=False,
        mqtt_topic=mqtt_topic,
        log_path=os.getenv("TELEMETRY_LOG_PATH", str(Path(__file__).with_name("telemetry_history.txt"))),
    )

    mqtt_manager = MqttManager(
        broker=os.getenv("MQTT_BROKER", "127.0.0.1"),
        port=environment_port("MQTT_PORT", 1883),
        sub_topic=mqtt_topic,
        username=mqtt_username,
        password=mqtt_password,
        on_message=web_app.update_telemetry,
        on_connection_change=web_app.set_mqtt_connected,
    )
    mqtt_manager.run_threaded()

    print("\n--- Central Dashboard Server Running ---")
    print(f"Web Dashboard: http://localhost:{web_app.port}")
    print("Press Ctrl+C to exit.\n")

    try:
        web_app.run()
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        mqtt_manager.stop()


if __name__ == "__main__":
    main()
