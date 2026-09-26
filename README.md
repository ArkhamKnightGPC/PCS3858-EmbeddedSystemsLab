# PCS 3858: Embedded Systems Laboratory

This repository contains the group project for the course [**PCS 3858: Embedded Systems Laboratory**](https://uspdigital.usp.br/jupiterweb/obterDisciplina?sgldis=PCS3858&verdis=1) at the University of São Paulo.

Open electronics project for a biometric monitoring system with [ESP32](https://en.wikipedia.org/wiki/ESP32) based modular wearable sensor modules and a [Rasperry Pi 3B+](https://www.raspberrypi.com/products/raspberry-pi-3-model-b-plus/) based central monitoring dashboard. Wireless communication of the sensor data collected at the ESP32 based sensor nodes is transmitted via [MQTT](https://mqtt.org/) to a [Mosquitto broker](https://mosquitto.org/) hosted at the Raspberry Pi.

## Wire color code

| Signal    | Color     |
| --------  | -------   |
| 3.3V      | red       |
| GND       | black     |
| SCL       | yellow    |
| SDA       | blue      |

## Reference Links

- [ESP32-C3-MINI-1 datasheet](https://documentation.espressif.com/esp32-c3-mini-1_datasheet_en.pdf)
- [Vibration Motor datasheet](https://dynamic.me/index.php?route=product/product/download&pdf=244&document_id=2258)
- [MPU-6050 Adafruit library](https://thinkrobotics.com/blogs/tutorials/mpu6050-tutorial-complete-guide-to-arduino-motion-sensing-for-robotics?srsltid=AU7gw4VchZZtGeOV7VDctssY_GERE_-E5XZ9nzlNcVwggXjlix6Jmn8V)
- [SparkFun MAX301x Particle Sensor Library](https://github.com/sparkfun/sparkfun_max3010x_sensor_library)
- [NTC 20K Thermistor celsius temperature characteristic](https://prod-edam.honeywell.com/content/dam/honeywell-edam/hbt/en-us/documents/literature-and-specs/datasheets/centraline/hbt-bms-en0b0476-ge51r0319.pdf?download=false)