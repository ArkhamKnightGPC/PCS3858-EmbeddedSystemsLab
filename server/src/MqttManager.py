from __future__ import annotations

import json
import logging
import random
import sys
from collections.abc import Callable
from typing import Any

from paho.mqtt import client as mqtt_client

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

MessageCallback = Callable[[dict[str, Any]], None]
ConnectionCallback = Callable[[bool], None]


class MqttManager:
    """Maintain the MQTT subscription and forward decoded JSON messages."""

    def __init__(
        self,
        broker: str,
        port: int,
        sub_topic: str,
        on_message: MessageCallback,
        on_connection_change: ConnectionCallback | None = None,
        username: str | None = None,
        password: str | None = None,
    ):
        self.broker = broker
        self.port = port
        self.sub_topic = sub_topic
        self.on_message_callback = on_message
        self.on_connection_change = on_connection_change
        self.client_id = f"rpi-central-{random.randint(0, 999_999):06d}"

        try:
            self.client = mqtt_client.Client(
                mqtt_client.CallbackAPIVersion.VERSION2,
                client_id=self.client_id,
            )
        except AttributeError:
            # Compatibility with paho-mqtt versions older than 2.0.
            self.client = mqtt_client.Client(client_id=self.client_id)

        if username:
            self.client.username_pw_set(username, password)

        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._setup_callbacks()

    def _set_connection_state(self, connected: bool) -> None:
        if self.on_connection_change is not None:
            self.on_connection_change(connected)

    def _setup_callbacks(self) -> None:
        def on_connect(client, userdata, flags, reason_code, properties=None):
            if reason_code == 0:
                logger.info(
                    "Connected to MQTT broker at %s:%d",
                    self.broker,
                    self.port,
                )
                result, _ = client.subscribe(self.sub_topic, qos=0)
                if result == mqtt_client.MQTT_ERR_SUCCESS:
                    logger.info("Subscribed to topic: %s", self.sub_topic)
                    self._set_connection_state(True)
                else:
                    logger.error(
                        "Could not subscribe to %s (error %d)",
                        self.sub_topic,
                        result,
                    )
                    self._set_connection_state(False)
            else:
                logger.error("MQTT connection rejected: %s", reason_code)
                self._set_connection_state(False)

        def on_disconnect(client, userdata, *args):
            self._set_connection_state(False)
            logger.warning("Disconnected from MQTT broker")

        def on_message(client, userdata, message):
            try:
                payload = json.loads(message.payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                logger.warning(
                    "Ignoring invalid JSON received on %s: %s",
                    message.topic,
                    error,
                )
                return

            if not isinstance(payload, dict):
                logger.warning(
                    "Ignoring non-object JSON received on %s", message.topic
                )
                return

            try:
                self.on_message_callback(payload)
            except (TypeError, ValueError) as error:
                logger.warning(
                    "Ignoring invalid telemetry received on %s: %s",
                    message.topic,
                    error,
                )
                return

            logger.info("Telemetry received on %s: %s", message.topic, payload)

        self.client.on_connect = on_connect
        self.client.on_disconnect = on_disconnect
        self.client.on_message = on_message

    def run_threaded(self) -> None:
        """Start paho's network loop and reconnect automatically if needed."""
        self.client.connect_async(self.broker, self.port, keepalive=60)
        self.client.loop_start()
        logger.info("MQTT network loop started")

    def stop(self) -> None:
        """Stop the network loop and close the broker connection."""
        self.client.disconnect()
        self.client.loop_stop()
