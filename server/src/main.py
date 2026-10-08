import time
import threading
import numpy as np

from WebApp import WebApp
from MqttManager import MqttManager

LOCK = threading.Lock()

def background_task(app_instance: WebApp):
    """Simulates metric updates or sensor data processing."""
    while True:
        values = get_values()
        with LOCK:
            app_instance.value = int(values[0]) # TO BE REPLACED with real sensor data...
        time.sleep(1)

def get_values() -> np.ndarray:
    """Generate mock sensor readings."""
    return np.random.randint(0, 100, 100)

if __name__ == "__main__":
    # 1. Initialize WebApp
    web_app = WebApp(host="0.0.0.0", port=5000, debug=False)

    # 2. Start WebApp in dedicated daemon thread => doesn't block main
    flask_thread = threading.Thread(target=web_app.run, daemon=True)
    flask_thread.start()

    # 3. Start MQTT Client Thread (connects to local Mosquitto broker on Raspberry Pi)
    mqtt_manager = MqttManager(broker='127.0.0.1', port=1883, sub_topic="measures", pub_topic="motor")
    mqtt_manager.run_threaded()

    # feed mock data to WebApp => to be replaced...
    update_thread = threading.Thread(target=background_task, args=(web_app,), daemon=True)
    update_thread.start()

    print("\n--- Central Dashboard Server Running ---")
    print("Web Dashboard: http://localhost:5000")
    print("Press Ctrl+C to exit.\n")

    try:
        while True: # keep main thread alive
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down server...")