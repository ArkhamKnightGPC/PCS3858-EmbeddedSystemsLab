"""Run the actual sketch logic on the host with disconnected hardware doubles.

This checks scheduling and serialization, not ESP32 drivers or physical timing.
Compilation must be run under job-guard, like the ESP32 build.
"""
import json
import re
import subprocess
from pathlib import Path

from WebApp import WebApp


STUBS = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <cstdarg>
#include <algorithm>
#include <string>
using std::min;
using byte = unsigned char;
unsigned long fakeTime = 0;
unsigned long millis() { return fakeTime; }
void delay(unsigned long ms) { fakeTime += ms; }
enum { HIGH = 1, LOW = 0, INPUT_PULLUP = 2, OUTPUT = 3,
       WL_CONNECTED = 4, WIFI_STA = 5, I2C_SPEED_FAST = 400000,
       pdTRUE = 1, pdPASS = 1 };
void pinMode(int, int) {} void digitalWrite(int, int) {}
int digitalRead(int) { return HIGH; }
void analogReadResolution(int) {} int analogRead(int) { return 2048; }
struct SerialStub {
    void begin(int) {} void println(const char*) {}
    template<class... T> void printf(const char*, T...) {}
} Serial;
struct WireStub {
    void begin(int, int) {} void beginTransmission(int) {} void write(int) {}
    int endTransmission(bool = true) { return 4; }
    int requestFrom(uint8_t, uint8_t) { return 0; }
    int read() { return -1; } int available() { return 0; }
} Wire;
struct MAX30105 {
    bool begin(WireStub&, int) { return false; }
    void setup(int = 0, int = 0, int = 0, int = 0, int = 0, int = 0) {}
    void setPulseAmplitudeRed(int) {} void setPulseAmplitudeGreen(int) {}
    void check() {} bool available() { return false; }
    long getFIFOIR() { return 0; } void nextSample() {}
};
bool checkForBeat(long) { return false; }
struct IpStub { std::string toString() { return "127.0.0.1"; } };
struct WiFiStub {
    int status() { return 0; } void disconnect() {} void begin(const char*, const char*) {}
    void mode(int) {} IpStub localIP() { return {}; }
} WiFi;
struct EspStub { uint64_t getEfuseMac() { return 123; } } ESP;
struct WiFiClient {};
struct PubSubClient {
    PubSubClient(WiFiClient&) {}
    bool connected() { return false; } bool loop() { return false; }
    bool connect(const char*, const char*, const char*) { return false; }
    bool publish(const char*, const char*) { return false; }
    int state() { return -1; }
    void setServer(const char*, uint16_t) {} void setSocketTimeout(int) {}
    bool setBufferSize(size_t) { return true; }
};
struct Queue { size_t size; bool full; char data[4096]; };
using QueueHandle_t = Queue*;
QueueHandle_t xQueueCreate(int, size_t size) { return new Queue{size, false, {}}; }
int xQueueOverwrite(QueueHandle_t q, const void* data) {
    memcpy(q->data, data, q->size); q->full = true; return pdTRUE;
}
int xQueuePeek(QueueHandle_t q, void* data, int) {
    if (!q->full) return 0;
    memcpy(data, q->data, q->size); return pdTRUE;
}
int xQueueReceive(QueueHandle_t q, void* data, int wait) {
    int result = xQueuePeek(q, data, wait); q->full = false; return result;
}
void xQueueReset(QueueHandle_t q) { q->full = false; }
int xTaskCreate(void(*)(void*), const char*, int, void*, int, void*) { return pdPASS; }
void vTaskDelete(void*) {} void vTaskDelay(int) {} int pdMS_TO_TICKS(int ms) { return ms; }
'''

HARNESS = r'''
int main() {
    setup(); // Both sensors disconnected: setup must return.
    for (int i = 0; i < 1100; i++) loop();
    assert(telemetryQueue->full);
    puts(telemetryQueue->data);
    xQueueReset(telemetryQueue);
    for (int i = 0; i < 1100; i++) loop();
    assert(telemetryQueue->full); // A second publication without any MPU samples.
    puts(telemetryQueue->data);

    mpuAvailable = true;
    sampleIndex = BATCH_SIZE;
    for (int i = 0; i < BATCH_SIZE; i++) mpuBatch[i] = {-2.0f, 2.0f, -2.0f, 3.46f};
    publishBatchPayload(false, 3.46f);
    puts(telemetryQueue->data);
    assert(strlen(telemetryQueue->data) + 7 + strlen(MQTT_TOPIC) <= PAYLOAD_SIZE + 128);

    char small[4] = {};
    size_t offset = 0;
    assert(!appendPayload(small, sizeof(small), offset, "%s", "too long"));
    assert(offset == 0);
    sendCancelMessage(); // Must retain cancellation even while MQTT is offline.
    assert(cancelQueue->full && sampleIndex == 0);
    delete telemetryQueue; delete cancelQueue;
}
'''


def test_sketch_publishes_without_sensors_and_serializes_full_batch(tmp_path):
    sketch_dir = Path(__file__).resolve().parents[2] / "wearable_esp32"
    sketch = (sketch_dir / "wearable_esp32.ino").read_text()
    # Hardware includes are replaced by interfaces above; local credentials are
    # never read. Keep all production function bodies and control flow intact.
    sketch = re.sub(r'#if __has_include\("secrets.h"\).*?#endif', '', sketch, flags=re.S)
    sketch = re.sub(r'^#include.*$', '', sketch, flags=re.M)
    credentials = (sketch_dir / "secrets.example.h").read_text().replace("#pragma once", "")
    source = tmp_path / "firmware_test.cpp"
    source.write_text(STUBS + credentials + sketch + HARNESS)
    binary = tmp_path / "firmware_test"
    subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-fsanitize=address,undefined",
                    str(source), "-o", str(binary)], check=True, timeout=30, capture_output=True)
    result = subprocess.run([str(binary)], check=True, timeout=5, capture_output=True, text=True)
    messages = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(messages) == 3
    assert not messages[0]["mpu_valid"] and messages[0]["accel_batch"] == []
    assert not messages[1]["heart_rate_valid"]
    assert len(messages[2]["accel_batch"]) == 50
    app = WebApp(log_path=tmp_path / "history.txt")
    for message in messages:
        app.update_telemetry(message)
    assert app.telemetry_snapshot()["sample_id"] == 3
