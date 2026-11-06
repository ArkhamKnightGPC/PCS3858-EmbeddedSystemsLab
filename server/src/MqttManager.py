from __future__ import annotations

import json
import logging
import sys
import uuid
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
        self.client_id = f"rpi-central-{uuid.uuid4().hex[:12]}"
        self.client = mqtt_client.Client(
            mqtt_client.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
        )

        if username:
            self.client.username_pw_set(username, password)

        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._setup_callbacks()

    def _set_connection_state(self, connected: bool) -> None:
        if self.on_connection_change is not None:
            self.on_connection_change(connected)

    def _setup_callbacks(self) -> None:
        def on_connect(client, userdata, flags, reason_code, properties=None):
            self._set_connection_state(False)
            if reason_code == 0:
                logger.info(
                    "Connected to MQTT broker at %s:%d",
                    self.broker,
                    self.port,
                )
                result, _ = client.subscribe(self.sub_topic, qos=0)
                if result == mqtt_client.MQTT_ERR_SUCCESS:
                    logger.info("Subscription requested for %s; waiting for SUBACK", self.sub_topic)
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

        def on_subscribe(client, userdata, mid, reason_codes, properties=None):
            accepted = bool(reason_codes) and all(not code.is_failure for code in reason_codes)
            self._set_connection_state(accepted)
            if accepted:
                logger.info("Subscription confirmed: %s", self.sub_topic)
            else:
                logger.error("Broker rejected subscription to %s: %s", self.sub_topic, reason_codes)

        def on_connect_fail(client, userdata):
            self._set_connection_state(False)
            logger.warning("MQTT TCP connection failed at %s:%d; retrying", self.broker, self.port)

        def on_message(client, userdata, message):
            # The wearable publishes live, non-retained telemetry. Old retained
            # falls/cancellations must not be replayed after a reconnect.
            if message.retain or len(message.payload) > 16384:
                logger.warning("Ignoring retained or oversized telemetry on %s", message.topic)
                return
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

            logger.debug("Telemetry received on %s", message.topic)

        self.client.on_connect = on_connect
        self.client.on_disconnect = on_disconnect
        self.client.on_message = on_message
        self.client.on_subscribe = on_subscribe
        self.client.on_connect_fail = on_connect_fail

    def run_threaded(self) -> None:
        """Start paho's network loop and reconnect automatically if needed."""
        self.client.connect_async(self.broker, self.port, keepalive=60)
        self.client.loop_start()
        logger.info("MQTT network loop started")

    def stop(self) -> None:
        """Stop the network loop and close the broker connection."""
        self.client.disconnect()
        self.client.loop_stop()
