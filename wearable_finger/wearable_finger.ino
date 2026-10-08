#include <Arduino.h>
#include <Wire.h>
#include "MAX30105.h"
#include "heartRate.h"

// --- Hardware Pin Definitions ---
const int adcPin = 34; // NTC 20k thermistor connected to GPIO 34 (ADC1_6)

// --- NTC 20k Parameters ---
const float R_REF = 20000.0;        // Fixed 20k resistor value (ohms)
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

// --- Timing Control Variables ---
unsigned long lastTempReadTime = 0;
const unsigned long TEMP_INTERVAL = 1000; // Read temperature every 1000ms (1 second)

// Variable to store latest temperature reading
float currentTempC = 0.0;
bool validTempRead = false;

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("Initializing System...");

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
}

void loop() {
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
  // 2. NTC 20k Temperature Reading (Runs every 1 second non-blocking)
  // -------------------------------------------------------------
  if (millis() - lastTempReadTime >= TEMP_INTERVAL) {
    lastTempReadTime = millis();

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

    // -------------------------------------------------------------
    // 3. Output Combined Data to Serial Monitor
    // -------------------------------------------------------------
    Serial.print("IR: ");
    Serial.print(irValue);
    Serial.print(" | BPM: ");
    Serial.print(beatsPerMinute, 1);
    Serial.print(" | Avg BPM: ");
    Serial.print(beatAvg);

    if (irValue < 50000) {
      Serial.print(" [No Finger Detected]");
    }

    Serial.print(" || Temp: ");
    if (validTempRead) {
      Serial.print(currentTempC, 1);
      Serial.println(" °C");
    } else {
      Serial.println("Out of Bounds!");
    }
  }
}