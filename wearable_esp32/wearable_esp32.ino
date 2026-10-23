#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include "MAX30105.h"
#include "heartRate.h"
#include "secrets.h"

// --- Configuration MPU6050 ---
const uint8_t MPU6050_ADDR = 0x68; // Endereço I2C padrão (AD0 em GND)
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
const int adcPin = 34; // NTC 20k thermistor connected to GPIO 34 (ADC1_6)

// --- NTC 20k Parameters ---
const float R_REF = 20000.0;        
const float NOMINAL_R = 20000.0;    // Resistance at 25°C (20k ohms)
const float NOMINAL_T = 25.0;       // Nominal temperature in °C
const float B_COEFFICIENT = 3950.0; // Beta value

// --- MAX30102 Parameters ---
MAX30105 particleSensor;
const byte RATE_SIZE = 4;
byte rates[RATE_SIZE];
byte rateSpot = 0;
long lastBeat = 0;
float beatsPerMinute = 0;
int beatAvg = 0;

// --- MPU6050 Sensor Variables ---
int16_t rawAx = 0, rawAy = 0, rawAz = 0;
int16_t rawGx = 0, rawGy = 0, rawGz = 0;
float ax = 0.0, ay = 0.0, az = 0.0; // Aceleração em g (±2g scale: 16384 LSB/g)
float gx = 0.0, gy = 0.0, gz = 0.0; // Velocidade angular em °/s (±250 deg/s scale: 131 LSB/deg/s)
bool mpuAvailable = false;

// --- Timing Control Variables ---
unsigned long lastSensorReadTime = 0;
const unsigned long SENSOR_INTERVAL = 1000; // Read NTC & MPU6050 every 1000ms (1 second)

// Variable to store latest temperature reading
float currentTempC = 0.0;
bool validTempRead = false;

// --- MPU6050 Driver Functions ---
bool initMPU6050() {
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(MPU6050_PWR_MGMT_1);
  Wire.write(0x00); // Tira o MPU6050 do modo Sleep
  return (Wire.endTransmission() == 0);
}

void readMPU6050() {
  if (!mpuAvailable) return;

  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(MPU6050_ACCEL_XOUT_H);
  if (Wire.endTransmission(false) != 0) {
    return;
  }

  // Solicita 14 bytes: Accel(6B) + Temp(2B) + Gyro(6B)
  if (Wire.requestFrom((uint8_t)MPU6050_ADDR, (uint8_t)14) == 14) {
    rawAx = (Wire.read() << 8) | Wire.read();
    rawAy = (Wire.read() << 8) | Wire.read();
    rawAz = (Wire.read() << 8) | Wire.read();

    // Ignora o registrador de temperatura interna do MPU6050 (2 bytes)
    Wire.read(); Wire.read();

    rawGx = (Wire.read() << 8) | Wire.read();
    rawGy = (Wire.read() << 8) | Wire.read();
    rawGz = (Wire.read() << 8) | Wire.read();

    // Conversão para unidades físicas
    ax = rawAx / 16384.0f;
    ay = rawAy / 16384.0f;
    az = rawAz / 16384.0f;

    gx = rawGx / 131.0f;
    gy = rawGy / 131.0f;
    gz = rawGz / 131.0f;
  }
}

void connectToWifi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  unsigned long now = millis();
  if (lastWifiConnectionAttempt != 0 &&
      now - lastWifiConnectionAttempt < WIFI_RECONNECT_INTERVAL) {
    return;
  }

  lastWifiConnectionAttempt = now;
  Serial.printf("Connecting to Wi-Fi network %s...\n", WIFI_SSID);
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void connectToMqtt() {
  if (WiFi.status() != WL_CONNECTED || mqttClient.connected()) {
    return;
  }

  unsigned long now = millis();
  if (lastMqttConnectionAttempt != 0 &&
      now - lastMqttConnectionAttempt < MQTT_RECONNECT_INTERVAL) {
    return;
  }

  lastMqttConnectionAttempt = now;

  uint64_t chipId = ESP.getEfuseMac();
  char clientId[32];
  snprintf(clientId, sizeof(clientId), "wearable-finger-%04X",
           static_cast<unsigned int>(chipId & 0xFFFFULL));

  Serial.printf("Connecting to MQTT broker %s:%u...\n", MQTT_BROKER, MQTT_PORT);
  if (mqttClient.connect(clientId, MQTT_USERNAME, MQTT_PASSWORD)) {
    Serial.println("Connected to MQTT broker.");
  } else {
    Serial.printf("MQTT connection failed (state %d).\n", mqttClient.state());
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

void publishMeasurements(long irValue) {
  if (!mqttClient.connected()) {
    Serial.println("Measurement not published: MQTT is disconnected.");
    return;
  }

  char payload[512];
  const bool fingerDetected = irValue >= 50000;

  char tempStr[16];
  if (validTempRead) {
    snprintf(tempStr, sizeof(tempStr), "%.1f", currentTempC);
  } else {
    snprintf(tempStr, sizeof(tempStr), "null");
  }

  snprintf(payload, sizeof(payload),
           "{"
           "\"ir\":%ld,\"bpm\":%.1f,\"avg_bpm\":%d,\"finger_detected\":%s,"
           "\"temperature_c\":%s,\"temperature_valid\":%s,"
           "\"accel\":{\"x\":%.2f,\"y\":%.2f,\"z\":%.2f},"
           "\"gyro\":{\"x\":%.2f,\"y\":%.2f,\"z\":%.2f},"
           "\"mpu_valid\":%s"
           "}",
           irValue, beatsPerMinute, beatAvg,
           fingerDetected ? "true" : "false",
           tempStr, validTempRead ? "true" : "false",
           ax, ay, az,
           gx, gy, gz,
           mpuAvailable ? "true" : "false");

  if (!mqttClient.publish(MQTT_TOPIC, payload)) {
    Serial.println("Failed to publish MQTT measurement.");
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("Initializing System...");

  WiFi.mode(WIFI_STA);
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setBufferSize(512); // Buffer expandido para comportar o payload JSON maior
  connectToWifi();

  // Initialize ADC Resolution for ESP32
  analogReadResolution(12);

  // Initialize I2C bus on ESP32-WROOM-DA default pins (SDA=21, SCL=22)
  Wire.begin(21, 22);

  // Initialize MAX30102 Sensor
  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("MAX30102 was not found. Please check wiring/power.");
    while (1);
  }

  Serial.println("MAX30102 found! Place your finger on the sensor with steady pressure.");

  particleSensor.setup();
  particleSensor.setPulseAmplitudeRed(0x0A); // Turn Red LED low for indication
  particleSensor.setPulseAmplitudeGreen(0);  // Turn off Green LED

  // Initialize MPU6050 Sensor
  if (initMPU6050()) {
    mpuAvailable = true;
    Serial.println("MPU6050 found and initialized!");
  } else {
    mpuAvailable = false;
    Serial.println("MPU6050 was not found on I2C bus. Check AD0 / wiring.");
  }
}

void loop() {
  maintainNetworkConnections();

  // -------------------------------------------------------------
  // 1. MAX30102 Heart Rate Processing (Runs continuously)
  // -------------------------------------------------------------
  long irValue = particleSensor.getIR();

  if (checkForBeat(irValue) == true) {
    long delta = millis() - lastBeat;
    lastBeat = millis();

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

  // -------------------------------------------------------------
  // 2. NTC 20k & MPU6050 Reading (Runs every 1 second non-blocking)
  // -------------------------------------------------------------
  if (millis() - lastSensorReadTime >= SENSOR_INTERVAL) {
    lastSensorReadTime = millis();

    // Read NTC Thermistor
    int rawValue = analogRead(adcPin);
    float voltage = (rawValue / 4095.0) * 3.3;

    if (voltage > 0.05 && voltage < 3.25) {
      float rNtc = R_REF * ((3.3 / voltage) - 1.0);
      float tempKelvin = 1.0 / ((1.0 / (NOMINAL_T + 273.15)) + (log(rNtc / NOMINAL_R) / B_COEFFICIENT));
      currentTempC = tempKelvin - 273.15;
      validTempRead = true;
    } else {
      validTempRead = false;
    }

    // Read MPU6050 Accelerometer and Gyroscope
    readMPU6050();

    // -------------------------------------------------------------
    // 3. Publish Combined Data to MQTT
    // -------------------------------------------------------------
    publishMeasurements(irValue);
  }
}