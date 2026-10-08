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
python3 main.py
```
