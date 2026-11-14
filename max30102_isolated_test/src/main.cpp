#include <Arduino.h>
#include <Wire.h>
#include <esp_system.h>
#include "MAX30105.h"

// Reuse the project's configuration driver. Read FIFO directly to avoid its
// four-slot software ring and to reject incomplete I2C transactions.
constexpr uint8_t ADDRESS = 0x57;
constexpr int SDA_PIN = 21;
constexpr int SCL_PIN = 22;
constexpr uint32_t I2C_HZ = 100000;
MAX30105 sensor;
bool ready = false;
uint32_t lastInit = 0, lastData = 0, lastStatus = 0;
uint32_t sequence = 0, windowSamples = 0, busErrors = 0, overflows = 0;
uint32_t redMin = UINT32_MAX, redMax = 0, irMin = UINT32_MAX, irMax = 0;
uint64_t redSum = 0, irSum = 0;
uint8_t latestWrite = 0, latestRead = 0, latestOverflow = 0;
uint32_t lastRecovery = 0;

bool readBytes(uint8_t reg, uint8_t* data, size_t length) {
  Wire.beginTransmission(ADDRESS);
  Wire.write(reg);
  uint8_t error = Wire.endTransmission(false);
  if (error != 0) {
    ++busErrors;
    Serial.printf("{\"type\":\"i2c_error\",\"ms\":%lu,\"reg\":%u,\"stage\":\"address\",\"code\":%u}\n",
                  millis(), reg, error);
    return false;
  }
  size_t received = Wire.requestFrom(ADDRESS, static_cast<uint8_t>(length));
  if (received != length || Wire.available() < static_cast<int>(length)) {
    ++busErrors;
    while (Wire.available()) Wire.read();
    Serial.printf("{\"type\":\"i2c_error\",\"ms\":%lu,\"reg\":%u,\"stage\":\"read\",\"expected\":%u,\"received\":%u}\n",
                  millis(), reg, static_cast<unsigned>(length), static_cast<unsigned>(received));
    return false;
  }
  for (size_t i = 0; i < length; ++i) data[i] = Wire.read();
  return true;
}

bool writeRegister(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(ADDRESS);
  Wire.write(reg);
  Wire.write(value);
  uint8_t error = Wire.endTransmission();
  if (error) {
    ++busErrors;
    Serial.printf("{\"type\":\"i2c_error\",\"ms\":%lu,\"reg\":%u,\"stage\":\"write\",\"code\":%u}\n",
                  millis(), reg, error);
  }
  return error == 0;
}

bool initializeSensor() {
  uint8_t identity[2];
  if (!readBytes(0xFE, identity, 2)) return false;
  Serial.printf("{\"type\":\"identity\",\"ms\":%lu,\"part_id\":%u,\"revision_id\":%u}\n",
                millis(), identity[1], identity[0]);
  if (identity[1] != 0x15) return false;
  if (!sensor.begin(Wire, I2C_HZ, ADDRESS)) return false;
  // Same settings as the project: red + IR, 400 Hz / 4 averaging = 100 Hz.
  sensor.setup(0x1F, 4, 2, 400, 411, 4096);
  sensor.setPulseAmplitudeRed(0x0A);
  sensor.setPulseAmplitudeGreen(0);
  uint8_t fifo, mode, spo2, red, ir;
  if (!readBytes(0x08, &fifo, 1) || !readBytes(0x09, &mode, 1) ||
      !readBytes(0x0A, &spo2, 1) || !readBytes(0x0C, &red, 1) || !readBytes(0x0D, &ir, 1)) return false;
  // Only averaging and rollover are configured by setup(). The low nibble is
  // the almost-full interrupt threshold; polling acquisition does not use it.
  bool valid = (fifo & 0xF0) == 0x50 && mode == 0x03 && spo2 == 0x2F && red == 0x0A && ir == 0x1F;
  Serial.printf("{\"type\":\"config\",\"ms\":%lu,\"valid\":%s,\"fifo\":%u,\"mode\":%u,\"spo2\":%u,\"red_current\":%u,\"ir_current\":%u}\n",
                millis(), valid ? "true" : "false", fifo, mode, spo2, red, ir);
  if (!valid) return false;
  uint8_t status;
  if (!readBytes(0x00, &status, 1)) return false; // Clear power-up status.
  lastData = millis();
  return true;
}

void readSamples() {
  uint8_t pointers[3]; // write pointer, overflow counter, read pointer
  // Match the original driver's single-register pointer transactions. Keep
  // pointer readback visible to distinguish FIFO loss from missing samples.
  if (!readBytes(0x04, &pointers[0], 1) ||
      !readBytes(0x05, &pointers[1], 1) ||
      !readBytes(0x06, &pointers[2], 1)) { ready = false; return; }
  latestWrite = pointers[0]; latestOverflow = pointers[1]; latestRead = pointers[2];
  uint8_t count = (pointers[0] - pointers[2]) & 0x1F;
  if (pointers[1]) {
    ++overflows;
    Serial.printf("{\"type\":\"fifo_overflow\",\"ms\":%lu,\"counter\":%u,\"write\":%u,\"read\":%u}\n",
                  millis(), pointers[1], pointers[0], pointers[2]);
    if (!writeRegister(0x05, 0)) { ready = false; return; }
    // A zero difference with overflow cannot distinguish a full FIFO from an
    // empty one. Reset pointers rather than label potentially stale data valid.
    if (!count) {
      if (!writeRegister(0x04, 0) || !writeRegister(0x06, 0)) ready = false;
      delay(10);
      return;
    }
  }
  while (count) {
    uint8_t block[30];
    uint8_t chunk = count > 5 ? 5 : count;
    if (!readBytes(0x07, block, chunk * 6)) { ready = false; return; }
    const uint32_t batchReadMs = millis();
    for (uint8_t i = 0; i < chunk; ++i) {
      const uint8_t* b = &block[i * 6];
      uint32_t red = ((uint32_t(b[0]) << 16) | (uint32_t(b[1]) << 8) | b[2]) & 0x3FFFF;
      uint32_t ir = ((uint32_t(b[3]) << 16) | (uint32_t(b[4]) << 8) | b[5]) & 0x3FFFF;
      ++sequence; ++windowSamples;
      redMin = min(redMin, red); redMax = max(redMax, red); redSum += red;
      irMin = min(irMin, ir); irMax = max(irMax, ir); irSum += ir;
      // Timestamp is FIFO read time, not the time of optical conversion.
      Serial.printf("{\"type\":\"sample\",\"seq\":%lu,\"ms\":%lu,\"red\":%lu,\"ir\":%lu,\"gap\":%s}\n",
                    sequence, batchReadMs, red, ir, pointers[1] ? "true" : "false");
    }
    lastData = millis();
    count -= chunk;
  }
}

void reportStatus() {
  uint32_t now = millis();
  uint32_t interval = now - lastStatus;
  uint8_t status = 0;
  bool statusValid = ready && readBytes(0x00, &status, 1);
  if (ready && !statusValid) ready = false;
  Serial.printf("{\"type\":\"status\",\"ms\":%lu,\"ready\":%s,\"window_ms\":%lu,\"samples\":%lu,\"i2c_errors\":%lu,\"overflow_events\":%lu,\"status_valid\":%s,\"int_status\":%u,\"sample_age_ms\":%lu",
                now, ready ? "true" : "false", interval, windowSamples, busErrors, overflows,
                statusValid ? "true" : "false", status, now - lastData);
  if (windowSamples) {
    Serial.printf(",\"red_min\":%lu,\"red_max\":%lu,\"red_mean\":%.1f,\"ir_min\":%lu,\"ir_max\":%lu,\"ir_mean\":%.1f",
                  redMin, redMax, double(redSum)/windowSamples, irMin, irMax, double(irSum)/windowSamples);
  }
  Serial.println("}");
  if (ready) {
    uint8_t combined[3];
    bool combinedValid = readBytes(0x04, combined, 3);
    Serial.printf("{\"type\":\"fifo_pointers\",\"ms\":%lu,\"write\":%u,\"overflow\":%u,\"read\":%u,\"combined_valid\":%s",
                  millis(), latestWrite, latestOverflow, latestRead, combinedValid ? "true" : "false");
    if (combinedValid) Serial.printf(",\"combined\":[%u,%u,%u]", combined[0], combined[1], combined[2]);
    Serial.println("}");
  }
  if (statusValid && (status & 0x01)) {
    Serial.println("{\"type\":\"sensor_power_reset\"}");
    ready = false;
  }
  windowSamples = 0; redMin = irMin = UINT32_MAX; redMax = irMax = 0; redSum = irSum = 0;
  lastStatus = now;
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.printf("{\"type\":\"boot\",\"test\":\"max30102-isolated-v3\",\"reset_reason\":%d,\"sda\":%d,\"scl\":%d,\"i2c_hz\":%lu}\n",
                int(esp_reset_reason()), SDA_PIN, SCL_PIN, I2C_HZ);
  Wire.begin(SDA_PIN, SCL_PIN, I2C_HZ);
  Wire.setTimeOut(50);
  lastInit = millis();
  ready = initializeSensor();
  lastStatus = millis();
}

void loop() {
  if (!ready && millis() - lastInit >= 3000) {
    lastInit = millis();
    ready = initializeSensor();
  }
  if (ready) {
    readSamples();
    if (millis() - lastData > 2000) {
      Serial.printf("{\"type\":\"no_samples_timeout\",\"ms\":%lu}\n", millis());
      ready = false;
    }
  }
  if (millis() - lastStatus >= 1000) reportStatus();
  delay(2);
}
