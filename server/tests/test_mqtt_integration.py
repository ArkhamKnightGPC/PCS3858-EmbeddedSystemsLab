import asyncio
import json

from amqtt.broker import Broker
from pwdlib import PasswordHash
from paho.mqtt import client as mqtt

from MqttManager import MqttManager
from WebApp import WebApp
from test_telemetry import measurement


async def wait_for(predicate, timeout=6):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.025)


def test_authenticated_mqtt_to_sse_and_reconnect(tmp_path):
    async def scenario():
        passwords = tmp_path / "broker-passwords"
        passwords.write_text("test-wearable:" + PasswordHash.recommended().hash("test-only") + "\n")
        broker = Broker({
            "listeners": {"default": {"type": "tcp", "bind": "127.0.0.1:0"}},
            "plugins": {
                "amqtt.plugins.authentication.FileAuthPlugin": {"password_file": str(passwords)},
            },
        })
        await broker.start()
        port = broker._servers["default"].instance.sockets[0].getsockname()[1]
        app = WebApp(log_path=tmp_path / "history.txt")
        manager = MqttManager("127.0.0.1", port, "wearable/finger/measurements",
                              app.update_telemetry, app.set_mqtt_connected,
                              username="test-wearable", password="test-only")
        publisher = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        publisher.username_pw_set("test-wearable", "test-only")
        publisher.connect_async("127.0.0.1", port)
        publisher.loop_start()
        manager.run_threaded()
        try:
            await wait_for(lambda: app.telemetry_snapshot()["mqtt_connected"] and publisher.is_connected())
            publisher.publish(manager.sub_topic, json.dumps(measurement()), qos=1)
            await wait_for(lambda: app.telemetry_snapshot()["sample_id"] == 1)
            stream = app.app.test_client().get("/chart-data", buffered=False)
            try:
                snapshot = json.loads(next(stream.response).decode().removeprefix("data: "))
                assert snapshot["bpm"] == 72.4 and len(snapshot["accel_batch"]) == 50
            finally:
                stream.close()

            publisher.publish(manager.sub_topic, "malformed JSON", qos=1)
            publisher.publish(manager.sub_topic, json.dumps(measurement(mpu_valid=False, accel_batch=[])), qos=1)
            await wait_for(lambda: app.telemetry_snapshot()["sample_id"] == 2)

            # Close the server-side transport unexpectedly: paho must reconnect
            # and resubscribe automatically before a new publication is sent.
            handler = broker._sessions[manager.client_id][1]
            await handler.writer.close()
            await wait_for(lambda: not app.telemetry_snapshot()["mqtt_connected"])
            await wait_for(lambda: app.telemetry_snapshot()["mqtt_connected"])
            publisher.publish(manager.sub_topic, json.dumps(measurement(bpm=80)), qos=1)
            await wait_for(lambda: app.telemetry_snapshot()["sample_id"] == 3)
            assert app.telemetry_snapshot()["bpm"] == 80
        finally:
            publisher.disconnect()
            manager.client.disconnect()
            await asyncio.to_thread(publisher.loop_stop)
            await asyncio.to_thread(manager.client.loop_stop)
            await broker.shutdown()

    asyncio.run(scenario())
