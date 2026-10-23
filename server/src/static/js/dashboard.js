document.addEventListener("DOMContentLoaded", () => {
    const maximumSamples = 30;
    const chartContext = document.getElementById("heartRateChart").getContext("2d");
    const heartRateChart = new Chart(chartContext, {
        type: "line",
        data: {
            labels: [],
            datasets: [
                {
                    label: "Heart Rate (BPM)",
                    data: [],
                    borderColor: "#e74c3c",
                    backgroundColor: "rgba(231, 76, 60, 0.1)",
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3,
                    spanGaps: true
                },
                {
                    label: "Average BPM",
                    data: [],
                    borderColor: "#8e44ad",
                    borderWidth: 2,
                    borderDash: [6, 4],
                    fill: false,
                    tension: 0.3,
                    spanGaps: true
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            scales: {
                x: { title: { display: true, text: "Time" } },
                y: { suggestedMin: 40, suggestedMax: 160 }
            }
        }
    });

    const connectionStatus = document.getElementById("connection-status");
    const bpmValue = document.getElementById("bpm-val");
    const averageBpmValue = document.getElementById("avg-bpm-val");
    const irValue = document.getElementById("ir-val");
    const temperatureValue = document.getElementById("temp-val");
    const temperatureStatus = document.getElementById("temp-status");
    const fingerBox = document.getElementById("finger-box");
    const fingerText = document.getElementById("finger-text");
    const lastUpdate = document.getElementById("last-update");

    // MPU6050 DOM Elements
    const mpuStatus = document.getElementById("mpu-status");
    const accelX = document.getElementById("accel-x");
    const accelY = document.getElementById("accel-y");
    const accelZ = document.getElementById("accel-z");
    const gyroX = document.getElementById("gyro-x");
    const gyroY = document.getElementById("gyro-y");
    const gyroZ = document.getElementById("gyro-z");

    function displayNumber(value, digits = 0) {
        return typeof value === "number" ? value.toFixed(digits) : "--";
    }

    function setConnectionState(telemetry) {
        if (!telemetry.mqtt_connected) {
            connectionStatus.className = "status-badge offline";
            connectionStatus.innerText = "MQTT disconnected";
        } else if (telemetry.data_stale) {
            connectionStatus.className = "status-badge warning";
            connectionStatus.innerText = "Waiting for telemetry";
        } else {
            connectionStatus.className = "status-badge online";
            connectionStatus.innerText = "Live";
        }
    }

    function updateChart(telemetry) {
        if (telemetry.last_update === null || telemetry.data_stale) return;

        const labels = heartRateChart.data.labels;
        if (labels.length > 0 && labels[labels.length - 1] === telemetry.last_update) {
            return;
        }

        if (labels.length >= maximumSamples) {
            labels.shift();
            heartRateChart.data.datasets.forEach((dataset) => dataset.data.shift());
        }

        labels.push(telemetry.last_update);
        heartRateChart.data.datasets[0].data.push(telemetry.bpm);
        heartRateChart.data.datasets[1].data.push(telemetry.avg_bpm);
        heartRateChart.update("none");
    }

    const eventSource = new EventSource("/chart-data");

    eventSource.onmessage = (event) => {
        const telemetry = JSON.parse(event.data);
        setConnectionState(telemetry);

        bpmValue.innerText = displayNumber(telemetry.bpm, 1);
        averageBpmValue.innerText = displayNumber(telemetry.avg_bpm);
        irValue.innerText = displayNumber(telemetry.ir);
        lastUpdate.innerText = telemetry.last_update ?? "--";

        // Temperature status update
        if (telemetry.temperature_valid && typeof telemetry.temperature_c === "number") {
            temperatureValue.innerText = telemetry.temperature_c.toFixed(1);
            temperatureStatus.innerText = "Valid sensor reading";
        } else {
            temperatureValue.innerText = "--";
            temperatureStatus.innerText = "Temperature reading out of bounds";
        }

        // MPU6050 Motion status update
        const horizonLayer = document.getElementById("horizon-sky-ground");
        const pitchVal = document.getElementById("pitch-val");
        const rollVal = document.getElementById("roll-val");
        const gVal = document.getElementById("g-val");

        if (telemetry.mpu_valid) {
            const pitch = telemetry.pitch_deg ?? 0;
            const roll = telemetry.roll_deg ?? 0;

            pitchVal.innerText = pitch.toFixed(1);
            rollVal.innerText = roll.toFixed(1);
            gVal.innerText = (telemetry.accel_magnitude ?? 0).toFixed(2);

            // Translate pitch (2px per degree) and rotate roll
            const pitchOffset = pitch * 2; 
            horizonLayer.style.transform = `translateY(${pitchOffset}px) rotate(${-roll}deg)`;
        } else {
            pitchVal.innerText = "--";
            rollVal.innerText = "--";
            gVal.innerText = "--";
        }

        // Finger detection status update
        if (telemetry.last_update === null) {
            fingerBox.className = "alert-box alert-warning";
            fingerText.innerText = "Waiting for data";
        } else if (telemetry.data_stale) {
            fingerBox.className = "alert-box alert-warning";
            fingerText.innerText = "Telemetry is stale";
        } else if (telemetry.finger_detected) {
            fingerBox.className = "alert-box alert-normal";
            fingerText.innerText = "Finger detected";
        } else {
            fingerBox.className = "alert-box alert-warning";
            fingerText.innerText = "No finger detected";
        }

        updateChart(telemetry);
    };

    eventSource.onerror = () => {
        connectionStatus.className = "status-badge offline";
        connectionStatus.innerText = "Dashboard disconnected";
    };
});