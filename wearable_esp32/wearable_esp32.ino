#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include "MAX30105.h"
#include "heartRate.h"
#include "secrets.h"

// --- Configuration MPU6050 ---
const uint8_t MPU6050_ADDR = 0x68;
const uint8_t MPU6050_PWR_MGMT_1 = 0x6B;
const uint8_t MPU6050_ACCEL_XOUT_H = 0x3B;

// --- Network and MQTT Configuration ---
const char *MQTT_BROKER = "10.68.33.243";
const uint16_t MQTT_PORT = 1883;
const char *MQTT_TOPIC = "wearable/finger/measurements";

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

unsigned long lastWifiConnectionAttempt = 0;
unsigned long lastMqttConnectionAttempt = 0;
const unsigned long WIFI_RECONNECT_INTERVAL = 10000;
const unsigned long MQTT_RECONNECT_INTERVAL = 5000;

// --- Hardware Pin Definitions ---
const int adcPin = 34;

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
long lastBeat = 0;
float beatsPerMinute = 0;
int beatAvg = 0;
long currentIrValue = 0;

// --- MPU6050 Batching Variables ---
const int BATCH_SIZE = 50;
int sampleIndex = 0;

struct MpuSample {
  float ax, ay, az;
  float gx, gy, gz;
};

MpuSample mpuBatch[BATCH_SIZE];

bool mpuAvailable = false;

// --- Timing Control Variables ---
unsigned long lastMaxReadTime = 0;
const unsigned long MAX_READ_INTERVAL = 25; // 40 Hz Optical PPG sampling

unsigned long lastMpuReadTime = 0;
const unsigned long MPU_READ_INTERVAL = 20; // 50 Hz IMU sampling (dt = 20ms)

float currentTempC = 0.0;
bool validTempRead = false;

bool initMPU6050() {
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(MPU6050_PWR_MGMT_1);
  Wire.write(0x00);
  return (Wire.endTransmission() == 0);
}

bool readSingleMPUSample(MpuSample &sample) {
  if (!mpuAvailable) {
    mpuAvailable = initMPU6050();
    if (!mpuAvailable) return false;
  }

  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(MPU6050_ACCEL_XOUT_H);
  if (Wire.endTransmission(false) != 0) {
    return false;
  }

  if (Wire.requestFrom((uint8_t)MPU6050_ADDR, (uint8_t)14) == 14) {
    int16_t rawAx = (Wire.read() << 8) | Wire.read();
    int16_t rawAy = (Wire.read() << 8) | Wire.read();
    int16_t rawAz = (Wire.read() << 8) | Wire.read();

    Wire.read(); Wire.read(); // Skip MPU internal temp

    int16_t rawGx = (Wire.read() << 8) | Wire.read();
    int16_t rawGy = (Wire.read() << 8) | Wire.read();
    int16_t rawGz = (Wire.read() << 8) | Wire.read();

    sample.ax = rawAx / 16384.0f;
    sample.ay = rawAy / 16384.0f;
    sample.az = rawAz / 16384.0f;

    sample.gx = rawGx / 131.0f;
    sample.gy = rawGy / 131.0f;
    sample.gz = rawGz / 131.0f;

    return true;
  } else {
    while (Wire.available()) Wire.read();
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
  snprintf(clientId, sizeof(clientId), "wearable-finger-%04X", static_cast<unsigned int>(chipId & 0xFFFFULL));

  if (mqttClient.connect(clientId, MQTT_USERNAME, MQTT_PASSWORD)) {
    Serial.println("Connected to MQTT broker.");
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

void publishBatchPayload() {
  if (!mqttClient.connected()) return;

  // Buffer large enough for batch payload (~2.5 KB)
  static char payload[3072]; 
  const bool fingerDetected = currentIrValue >= 50000;

  char tempStr[16];
  if (validTempRead) {
    snprintf(tempStr, sizeof(tempStr), "%.1f", currentTempC);
  } else {
    snprintf(tempStr, sizeof(tempStr), "null");
  }

  int offset = snprintf(payload, sizeof(payload),
    "{"
    "\"ir\":%ld,\"bpm\":%.1f,\"avg_bpm\":%d,\"finger_detected\":%s,"
    "\"temperature_c\":%s,\"temperature_valid\":%s,"
    "\"mpu_valid\":%s,\"accel_batch\":[",
    currentIrValue, beatsPerMinute, beatAvg,
    fingerDetected ? "true" : "false",
    tempStr, validTempRead ? "true" : "false",
    mpuAvailable ? "true" : "false"
  );

  // Append batched samples
  for (int i = 0; i < BATCH_SIZE; i++) {
    offset += snprintf(payload + offset, sizeof(payload) - offset,
                       "[%.2f,%.2f,%.2f]%s",
                       mpuBatch[i].ax, mpuBatch[i].ay, mpuBatch[i].az,
                       (i < BATCH_SIZE - 1) ? "," : "");
  }

  snprintf(payload + offset, sizeof(payload) - offset, "]}");

  mqttClient.publish(MQTT_TOPIC, payload);
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  WiFi.mode(WIFI_STA);
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  
  // Expand MQTT buffer to hold 3 KB batch payload
  mqttClient.setBufferSize(3072);
  connectToWifi();

  analogReadResolution(12);
  Wire.begin(21, 22);

  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("MAX30102 non-responsive!");
    while (1);
  }

  particleSensor.setup();
  particleSensor.setPulseAmplitudeRed(0x0A);
  particleSensor.setPulseAmplitudeGreen(0);

  if (initMPU6050()) {
    mpuAvailable = true;
    Serial.println("MPU6050 initialized!");
  }
}

void loop() {
  maintainNetworkConnections();

  unsigned long currentMillis = millis();

  // 1. MAX30102 Processing (40 Hz)
  if (currentMillis - lastMaxReadTime >= MAX_READ_INTERVAL) {
    lastMaxReadTime = currentMillis;
    currentIrValue = particleSensor.getIR();

    if (checkForBeat(currentIrValue)) {
      long delta = currentMillis - lastBeat;
      lastBeat = currentMillis;

      beatsPerMinute = 60.0 / (delta / 1000.0);

      if (beatsPerMinute < 255 && beatsPerMinute > 20) {
        rates[rateSpot++] = (byte)beatsPerMinute;
        rateSpot %= RATE_SIZE;

        beatAvg = 0;
        for (byte x = 0; x < RATE_SIZE; x++) {
          beatAvg += rates[x];
        }
        beatAvg /= RATE_SIZE;
      }
    }
  }

  // 2. High-speed MPU6050 Batch Sampling (50 Hz / dt = 20ms)
  if (currentMillis - lastMpuReadTime >= MPU_READ_INTERVAL) {
    lastMpuReadTime = currentMillis;

    MpuSample sample;
    if (readSingleMPUSample(sample)) {
      mpuBatch[sampleIndex++] = sample;

      // When 50 samples are collected, read temperature and publish batch
      if (sampleIndex >= BATCH_SIZE) {
        readNtcTemperature();
        publishBatchPayload();
        sampleIndex = 0; // Reset batch buffer pointer
      }
    }
  }
}