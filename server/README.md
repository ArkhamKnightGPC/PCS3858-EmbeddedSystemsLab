# Central monitoring dashboard

The central monitoring dashboard is implemented on a Raspberry Pi 3B+ and has two components:

- an **MQTT broker** where the wearable device sensors can publish measurement data;
- and a **Python web server** hosting a [Flask](https://flask.palletsprojects.com/en/stable/) web-application that displays the measured sensor data.

## Setup

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

To launch the application on the Raspberry Pi, run
```
cd src/
export MQTT_USERNAME="your_mqtt_username"
export MQTT_PASSWORD="your_mqtt_password"
python3 main.py
```

The server connects to the local broker at `127.0.0.1:1883`, subscribes to
`wearable/finger/measurements`, and makes the latest wearable sample available
to the dashboard at `http://<raspberry-pi-ip>:5000`.

The connection can be changed without editing the source code:

```
export MQTT_BROKER="127.0.0.1"
export MQTT_PORT="1883"
export MQTT_TOPIC="wearable/finger/measurements"
export WEB_HOST="0.0.0.0"
export WEB_PORT="5000"
```
