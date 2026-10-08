import sys
import time
import json
import logging
import random

from datetime import datetime
from typing import Iterator
from flask import Flask, Response, render_template, request, stream_with_context

class WebApp:
    def __init__(self, host="0.0.0.0", port=5000, debug=False):
        self.app = Flask(__name__)
        self.host = host
        self.port = port
        self.debug = debug

        # Telemetry payload matching your wearable sensors
        self.telemetry = {
            "hr": 75,
            "spo2": 98,
            "temp": 36.5,
            "fall_alert": False
        }

        self.app.add_url_rule("/", "index", self.index)
        self.app.add_url_rule("/chart-data", "chart_data", self.chart_data)

    def index(self) -> str:
        # Flask automatically looks inside the /templates folder for index.html
        return render_template("index.html")

    def update_data(self) -> Iterator[str]:
        while True:
            payload = {
                "time": datetime.now().strftime("%H:%M:%S"),
                **self.telemetry
            }
            yield f"data:{json.dumps(payload)}\n\n"
            time.sleep(1) # Updates frontend according to telemetry rate

    def chart_data(self) -> Response:
        response = Response(stream_with_context(self.update_data()), mimetype="text/event-stream")
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        return response

    def run(self):
        self.app.run(host=self.host, port=self.port, debug=self.debug, use_reloader=False, threaded=True)