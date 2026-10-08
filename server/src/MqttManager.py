import sys
import random
import logging
import threading
import struct
import numpy as np
from typing import Any
from paho.mqtt import client as mqtt_client

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

LOCK = threading.Lock()

class MqttManager:
    """Class to handle the MQTT connection."""

    def __init__(self, broker: str, port: int, sub_topic: str, pub_topic: str):
        self.broker = broker
        self.port = port
        self.sub_topic = sub_topic
        self.pub_topic = pub_topic
        self.client_id = f'rpi-central-{random.randint(0, 1000)}'

        try:
            self.client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION2, client_id=self.client_id)
        except AttributeError:
            self.client = mqtt_client.Client(client_id=self.client_id)

        self.setup_callbacks()

    def setup_callbacks(self):
        def on_connect(client, userdata, flags, rc, properties=None):
            if rc == 0:
                logger.info("Connected to MQTT Broker @ %s:%d", self.broker, self.port)
                client.subscribe(self.sub_topic)
                logger.info("Subscribed to topic: %s", self.sub_topic)
            else:
                logger.error("Failed to connect, return code %d", rc)

        def on_message(client, userdata, msg):
            payload = msg.payload
            logger.info("MQTT Message received on [%s]: %s", msg.topic, payload)

            # Example binary unpack (if payload contains binary ints)
            if len(payload) >= 4 and len(payload) % 4 == 0:
                int_count = len(payload) // 4
                int_array = np.array(list(struct.unpack(f'{int_count}i', payload)))
                with LOCK:
                    logger.info("Unpacked Array: %s", int_array)

            self.publish("ok")

        self.client.on_connect = on_connect
        self.client.on_message = on_message

    def connect(self):
        try:
            self.client.connect(self.broker, self.port, keepalive=60)
        except Exception as e:
            logger.error("Could not connect to MQTT Broker: %s", e)

    def publish(self, msg: Any):
        result = self.client.publish(self.pub_topic, str(msg))
        if result[0] == 0:
            logger.info("Sent `%s` to topic `%s`", msg, self.pub_topic)
        else:
            logger.error("Failed to send message to topic %s", self.pub_topic)

    def run_threaded(self):
        self.connect()
        # loop_start() creates a background thread automatically for MQTT network processing
        self.client.loop_start()
        logger.info("MQTT Manager loop started in background.")