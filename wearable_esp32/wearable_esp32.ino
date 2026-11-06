#include <Arduino.h>
#include <WiFi.h>
#include "PubSubClient.h"
#include <stdarg.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/queue.h>
#include <Wire.h>
#include "MAX30105.h"
#include "heartRate.h"
#if __has_include("secrets.h")
#include "secrets.h"
#else
#include "secrets.example.h"
#endif

// --- Configuration MPU6050 ---
const int I2C_SDA_PIN = 21;
const int I2C_SCL_PIN = 22;
const uint8_t MPU6050_ADDR_LOW = 0x68;
const uint8_t MPU6050_ADDR_HIGH = 0x69;
const uint8_t MPU6050_PWR_MGMT_1 = 0x6B;
const uint8_t MPU6050_ACCEL_XOUT_H = 0x3B;
const uint8_t MPU6050_WHO_AM_I = 0x75;
uint8_t mpu6050Address = MPU6050_ADDR_LOW;

// --- Pin Definitions for LED Button ---
const int BUTTON_PIN = 13; // Connect button to GPIO 13 (Pull-up)
const int LED_PIN = 12;    // Connect LED to GPIO 12

// --- Network and MQTT Configuration ---
#ifndef WEARABLE_MQTT_BROKER
#define WEARABLE_MQTT_BROKER "10.197.100.243"
#endif
const char *MQTT_BROKER = WEARABLE_MQTT_BROKER;
const uint16_t MQTT_PORT = 1883;
const char *MQTT_TOPIC = "wearable/finger/measurements";

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);
const size_t PAYLOAD_SIZE = 3072;
struct TelemetryMessage { char payload[PAYLOAD_SIZE]; };
QueueHandle_t telemetryQueue;
QueueHandle_t cancelQueue;

unsigned long lastWifiConnectionAttempt = 0;
unsigned long lastMqttConnectionAttempt = 0;
const unsigned long WIFI_RECONNECT_INTERVAL = 10000;
const unsigned long MQTT_RECONNECT_INTERVAL = 5000;

const int adcPin = 34; // NTC 20k

// --- NTC 20k Parameters ---
const float R_REF = 20000.0;        
const float NOMINAL_R = 20000.0;    
const float NOMINAL_T = 25.0;       
const float B_COEFFICIENT = 3950.0; 

// --- MAX30102 Parameters ---
MAX30105 particleSensor;
const byte RATE_SIZE = 4;
byte rates[RATE_SIZE];
byte rateSpot = 0;
byte rateCount = 0;
unsigned long lastBeat = 0;
float beatsPerMinute = 0;
int beatAvg = 0;
long currentIrValue = 0;
bool maxAvailable = false;
unsigned long lastMaxInitAttempt = 0;

// --- MPU6050 Batching & Fall Variables ---
const int BATCH_SIZE = 50;
int sampleIndex = 0;

struct MpuSample {
  float ax, ay, az;
  float g_force; // Precomputed G-force magnitude per sample
};

MpuSample mpuBatch[BATCH_SIZE];
bool mpuAvailable = false;
bool activeFallAlert = false; // Tracks if LED should glow awaiting confirmation
bool batchFallDetected = false;
unsigned long lastMpuInitAttempt = 0;

// --- Timing Control Variables ---
unsigned long lastMaxReadTime = 0;
unsigned long lastPublishTime = 0;
const unsigned long PUBLISH_INTERVAL = 1000;

unsigned long lastMpuReadTime = 0;
const unsigned long MPU_READ_INTERVAL = 20; // 50 Hz IMU sampling

float currentTempC = 0.0;
bool validTempRead = false;

// Button debounce variables
unsigned long lastDebounceTime = 0;
const unsigned long DEBOUNCE_DELAY = 50;
int lastButtonState = HIGH;

void scanI2CBus() {
  int found = 0;
  Serial.print("I2C devices:");
  for (uint8_t address = 1; address < 127; address++) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0) {
      Serial.printf(" 0x%02X", address);
      found++;
    }
  }
  if (found == 0) Serial.print(" none");
  Serial.println();
}

bool readI2CRegister(uint8_t address, uint8_t reg, uint8_t &value) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0 || Wire.requestFrom(address, (uint8_t)1) != 1) {
    return false;
  }
  value = Wire.read();
  return true;
}

bool findMPU6050() {
  const uint8_t addresses[] = {MPU6050_ADDR_LOW, MPU6050_ADDR_HIGH};
  for (uint8_t address : addresses) {
    uint8_t whoAmI = 0;
    if (readI2CRegister(address, MPU6050_WHO_AM_I, whoAmI) &&
        (whoAmI == MPU6050_ADDR_LOW || whoAmI == MPU6050_ADDR_HIGH)) {
      mpu6050Address = address;
      return true;
    }
  }
  return false;
}

bool initMPU6050() {
  if (!findMPU6050()) return false;

  Wire.beginTransmission(mpu6050Address);
  Wire.write(MPU6050_PWR_MGMT_1);
  Wire.write(0x00);
  if (Wire.endTransmission() != 0) return false;

  delay(10);
  uint8_t whoAmI = 0;
  return readI2CRegister(mpu6050Address, MPU6050_WHO_AM_I, whoAmI) &&
         (whoAmI == MPU6050_ADDR_LOW || whoAmI == MPU6050_ADDR_HIGH);
}

bool readSingleMPUSample(MpuSample &sample) {
  if (!mpuAvailable) {
    if (millis() - lastMpuInitAttempt < 1000) return false;
    lastMpuInitAttempt = millis();
    mpuAvailable = initMPU6050();
    if (!mpuAvailable) return false;
  }

  Wire.beginTransmission(mpu6050Address);
  Wire.write(MPU6050_ACCEL_XOUT_H);
  if (Wire.endTransmission(false) != 0) {
    mpuAvailable = false;
    return false;
  }

  if (Wire.requestFrom(mpu6050Address, (uint8_t)14) == 14) {
    int16_t rawAx = (Wire.read() << 8) | Wire.read();
    int16_t rawAy = (Wire.read() << 8) | Wire.read();
    int16_t rawAz = (Wire.read() << 8) | Wire.read();

    Wire.read(); Wire.read(); // Skip temp

    Wire.read(); Wire.read();
    Wire.read(); Wire.read();
    Wire.read(); Wire.read(); // Skip gyro

    sample.ax = rawAx / 16384.0f;
    sample.ay = rawAy / 16384.0f;
    sample.az = rawAz / 16384.0f;

    // Corrected: Standard arithmetic multiplication
    sample.g_force = sqrt(sample.ax * sample.ax + sample.ay * sample.ay + sample.az * sample.az);

    return true;
  } else {
    while (Wire.available()) Wire.read();
    mpuAvailable = false;
    return false;
  }
}

void readNtcTemperature() {
  int rawValue = analogRead(adcPin);
  float voltage = (rawValue / 4095.0f) * 3.3f;

  if (voltage > 0.05f && voltage < 3.25f) {
    float rNtc = R_REF * ((3.3f / voltage) - 1.0f);
    if (rNtc > 0.0f) {
      float tempKelvin = 1.0f / ((1.0f / (NOMINAL_T + 273.15f)) + (log(rNtc / NOMINAL_R) / B_COEFFICIENT));
      currentTempC = tempKelvin - 273.15f;
      validTempRead = true;
      return;
    }
  }
  validTempRead = false;
}

void connectToWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  unsigned long now = millis();
  if (lastWifiConnectionAttempt != 0 && now - lastWifiConnectionAttempt < WIFI_RECONNECT_INTERVAL) return;

  lastWifiConnectionAttempt = now;
  Serial.println("Wi-Fi connection attempt...");
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void connectToMqtt() {
  if (WiFi.status() != WL_CONNECTED || mqttClient.connected()) return;
  unsigned long now = millis();
  if (lastMqttConnectionAttempt != 0 && now - lastMqttConnectionAttempt < MQTT_RECONNECT_INTERVAL) return;

  lastMqttConnectionAttempt = now;
  uint64_t chipId = ESP.getEfuseMac();
  char clientId[32];
  snprintf(clientId, sizeof(clientId), "wearable-%012llX", static_cast<unsigned long long>(chipId & 0xFFFFFFFFFFFFULL));
  Serial.printf("MQTT connecting to %s:%u; local IP %s\n", MQTT_BROKER,
                static_cast<unsigned int>(MQTT_PORT), WiFi.localIP().toString().c_str());
  if (mqttClient.connect(clientId, MQTT_USERNAME, MQTT_PASSWORD)) {
    Serial.println("MQTT connected.");
  } else {
    Serial.printf("MQTT failed: state=%d (-2 TCP, -4 timeout, 4 credentials, 5 unauthorized)\n", mqttClient.state());
  }
}

void maintainNetworkConnections() {
  if (WiFi.status() != WL_CONNECTED) {
    connectToWifi();
    return;
  }
  connectToMqtt();
  if (mqttClient.connected()) {
    mqttClient.loop();
  }
}

void sendCancelMessage() {
  const uint8_t pending = 1;
  xQueueOverwrite(cancelQueue, &pending);
  batchFallDetected = false;
  sampleIndex = 0;
  Serial.println("Fall cancellation queued.");
}

bool appendPayload(char *payload, size_t capacity, size_t &offset, const char *format, ...) {
  if (offset >= capacity) return false;
  va_list args;
  va_start(args, format);
  int written = vsnprintf(payload + offset, capacity - offset, format, args);
  va_end(args);
  if (written < 0 || static_cast<size_t>(written) >= capacity - offset) return false;
  offset += static_cast<size_t>(written);
  return true;
}

void publishBatchPayload(bool batchFallVerdict, float minGInBatch) {
  static TelemetryMessage message;
  char *payload = message.payload;
  const bool fingerDetected = currentIrValue >= 50000;

  char tempStr[16];
  if (validTempRead) {
    snprintf(tempStr, sizeof(tempStr), "%.1f", currentTempC);
  } else {
    snprintf(tempStr, sizeof(tempStr), "null");
  }

  size_t offset = 0;
  bool complete = appendPayload(payload, PAYLOAD_SIZE, offset,
    "{"
    "\"ir\":%ld,\"bpm\":%.1f,\"avg_bpm\":%d,\"finger_detected\":%s,"
    "\"temperature_c\":%s,\"temperature_valid\":%s,"
    "\"mpu_valid\":%s,\"fall_verdict\":\"%s\",\"min_g_dip\":%.2f,"
    "\"fall_canceled\":false,\"accel_batch\":[",
    currentIrValue, beatsPerMinute, beatAvg,
    fingerDetected ? "true" : "false",
    tempStr, validTempRead ? "true" : "false",
    mpuAvailable ? "true" : "false",
    batchFallVerdict ? "fall" : "no fall",
    minGInBatch
  );

  for (int i = 0; complete && i < sampleIndex; i++) {
    complete = appendPayload(payload, PAYLOAD_SIZE, offset,
                       "[%.2f,%.2f,%.2f,%.2f]%s",
                       mpuBatch[i].ax, mpuBatch[i].ay, mpuBatch[i].az, mpuBatch[i].g_force,
                       (i < sampleIndex - 1) ? "," : "");
  }

  complete = complete && appendPayload(payload, PAYLOAD_SIZE, offset, "]}");
  if (!complete) {
    Serial.println("Telemetry serialization failed: payload too large.");
    return;
  }
  xQueueOverwrite(telemetryQueue, &message);
}

// PubSubClient connect/loop can block. Only this task owns the network client;
// sensor acquisition and the physical cancellation button keep running.
void networkTask(void *) {
  static TelemetryMessage outgoing;
  WiFi.mode(WIFI_STA);
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setSocketTimeout(2);
  // MQTT also needs room for its header and topic, beyond the JSON payload.
  if (!mqttClient.setBufferSize(PAYLOAD_SIZE + 128)) {
    Serial.println("Cannot allocate MQTT buffer.");
    vTaskDelete(nullptr);
    return;
  }
  for (;;) {
    maintainNetworkConnections();
    if (mqttClient.connected()) {
      uint8_t pending;
      if (xQueuePeek(cancelQueue, &pending, 0) == pdTRUE) {
        if (mqttClient.publish(MQTT_TOPIC, "{\"fall_canceled\":true}")) {
          xQueueReceive(cancelQueue, &pending, 0);
          // Drop any measurement queued before the cancellation.
          xQueueReset(telemetryQueue);
          Serial.println("MQTT cancellation sent.");
        } else {
          Serial.println("MQTT cancellation failed; retry pending.");
        }
      } else if (xQueueReceive(telemetryQueue, &outgoing, 0) == pdTRUE) {
        if (!mqttClient.publish(MQTT_TOPIC, outgoing.payload)) {
          Serial.printf("MQTT publish failed: bytes=%u, state=%d\n",
                        static_cast<unsigned int>(strlen(outgoing.payload)), mqttClient.state());
        } else {
          Serial.printf("MQTT published %u bytes on %s\n",
                        static_cast<unsigned int>(strlen(outgoing.payload)), MQTT_TOPIC);
        }
      }
    }
    vTaskDelay(pdMS_TO_TICKS(20));
  }
}

void checkButtonPress() {
  int reading = digitalRead(BUTTON_PIN);

  if (reading != lastButtonState) {
    lastDebounceTime = millis();
  }

  if ((millis() - lastDebounceTime) > DEBOUNCE_DELAY) {
    if (reading == LOW && activeFallAlert) {
      activeFallAlert = false;
      digitalWrite(LED_PIN, LOW); // Turning off LED indicator
      sendCancelMessage();        // Sending cancellation to Pi
    }
  }

  lastButtonState = reading;
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  Serial.printf("Starting wearable; MQTT destination %s:%u\n", MQTT_BROKER, static_cast<unsigned int>(MQTT_PORT));
  telemetryQueue = xQueueCreate(1, sizeof(TelemetryMessage));
  cancelQueue = xQueueCreate(1, sizeof(uint8_t));
  if (!telemetryQueue || !cancelQueue ||
      xTaskCreate(networkTask, "mqtt", 6144, nullptr, 1, nullptr) != pdPASS) {
    Serial.println("Cannot start MQTT task; check available memory.");
    while (true) delay(1000);
  }

  analogReadResolution(12);
  if (!Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN, I2C_SPEED_FAST)) {
    Serial.println("I2C initialization failed.");
  } else {
    Serial.printf("I2C ready: SDA=%d, SCL=%d\n", I2C_SDA_PIN, I2C_SCL_PIN);
    scanI2CBus();
  }

  maxAvailable = particleSensor.begin(Wire, I2C_SPEED_FAST);
  if (maxAvailable) {
    particleSensor.setup(0x1F, 4, 2, 400, 411, 4096);
    particleSensor.setPulseAmplitudeRed(0x0A);
    particleSensor.setPulseAmplitudeGreen(0);
    Serial.println("MAX30102 ready at 0x57.");
  } else {
    Serial.println("MAX30102 unavailable; other telemetry will continue.");
  }

  if (initMPU6050()) {
    mpuAvailable = true;
    Serial.printf("MPU6050 ready at 0x%02X.\n", mpu6050Address);
  } else {
    Serial.println("MPU6050 unavailable; publishing without acceleration.");
  }
}

void loop() {
  checkButtonPress();

  unsigned long currentMillis = millis();

  // Retry a missing optical sensor without stopping the rest of the device.
  if (!maxAvailable && currentMillis - lastMaxInitAttempt >= 5000) {
    lastMaxInitAttempt = currentMillis;
    maxAvailable = particleSensor.begin(Wire, I2C_SPEED_FAST);
    if (maxAvailable) {
      particleSensor.setup(0x1F, 4, 2, 400, 411, 4096);
      particleSensor.setPulseAmplitudeRed(0x0A);
      particleSensor.setPulseAmplitudeGreen(0);
    }
  }

  // Drain the sensor FIFO at its effective 100 Hz (400 Hz / 4 averaging).
  if (maxAvailable) particleSensor.check();
  while (maxAvailable && particleSensor.available()) {
    lastMaxReadTime = currentMillis;
    currentIrValue = particleSensor.getFIFOIR();
    particleSensor.nextSample();

    bool beat = checkForBeat(currentIrValue);
    if (currentIrValue < 50000) {
      beatsPerMinute = 0;
      beatAvg = 0;
      rateCount = 0;
      rateSpot = 0;
      lastBeat = 0;
    } else if (beat) {
      unsigned long delta = currentMillis - lastBeat;
      bool hadPreviousBeat = lastBeat != 0;
      lastBeat = currentMillis;
      float candidateBpm = delta ? 60000.0f / delta : 0.0f;

      if (hadPreviousBeat && candidateBpm < 255 && candidateBpm > 20) {
        beatsPerMinute = candidateBpm;
        rates[rateSpot++] = (byte)beatsPerMinute;
        rateSpot %= RATE_SIZE;
        if (rateCount < RATE_SIZE) rateCount++;
        beatAvg = 0;
        for (byte x = 0; x < rateCount; x++) beatAvg += rates[x];
        beatAvg /= rateCount;
      }
    }
  }

  // 2. High-speed MPU6050 Batch Sampling (50 Hz)
  if (currentMillis - lastMpuReadTime >= MPU_READ_INTERVAL) {
    lastMpuReadTime = currentMillis;

    MpuSample sample;
    if (readSingleMPUSample(sample)) {
      if (sampleIndex < BATCH_SIZE) mpuBatch[sampleIndex++] = sample;
      if (sample.g_force <= 0.3f) {
          batchFallDetected = true;
          activeFallAlert = true;
          digitalWrite(LED_PIN, HIGH);
      }
    } else {
      sampleIndex = 0;
      batchFallDetected = false;
    }
  }

  if (maxAvailable && currentMillis - lastMaxReadTime > 2000) {
    maxAvailable = false;
    currentIrValue = 0;
    Serial.println("MAX30102 stopped producing samples; retrying initialization.");
  }
  if (!maxAvailable || (lastBeat && currentMillis - lastBeat > 3000)) {
    beatsPerMinute = 0;
    beatAvg = 0;
    rateCount = 0;
    rateSpot = 0;
    lastBeat = 0;
  }

  // Publishing is time-driven, independent of either sensor's availability.
  if (currentMillis - lastPublishTime >= PUBLISH_INTERVAL) {
    lastPublishTime = currentMillis;
    float minG = sampleIndex ? mpuBatch[0].g_force : 1.0f;
    for (int i = 1; i < sampleIndex; i++) minG = min(minG, mpuBatch[i].g_force);
    readNtcTemperature();
    publishBatchPayload(batchFallDetected, minG);
    sampleIndex = 0;
    batchFallDetected = false;
  }
  delay(1);
}
