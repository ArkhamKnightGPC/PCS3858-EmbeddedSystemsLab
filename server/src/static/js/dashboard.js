document.addEventListener("DOMContentLoaded", () => {
    const maximumSamples = 20; // Reduzido para diminuir a carga de processamento

    // 1. Gráfico de Frequência Cardíaca
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
                    tension: 0.2,
                    spanGaps: true
                },
                {
                    label: "Average BPM",
                    data: [],
                    borderColor: "#8e44ad",
                    borderWidth: 2,
                    borderDash: [6, 4],
                    fill: false,
                    tension: 0.2,
                    spanGaps: true
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            elements: { point: { radius: 0 } },
            scales: {
                x: { title: { display: true, text: "Time" } },
                y: { suggestedMin: 40, suggestedMax: 160 }
            }
        }
    });

    // 2. Gráfico de Temperatura
    const tempChartContext = document.getElementById("temperatureChart").getContext("2d");
    const temperatureChart = new Chart(tempChartContext, {
        type: "line",
        data: {
            labels: [],
            datasets: [
                {
                    label: "Temperature (°C)",
                    data: [],
                    borderColor: "#f39c12",
                    backgroundColor: "rgba(243, 156, 18, 0.15)",
                    borderWidth: 2,
                    fill: true,
                    tension: 0.2,
                    spanGaps: true
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            elements: { point: { radius: 0 } },
            scales: {
                x: { title: { display: true, text: "Time" } },
                y: { suggestedMin: 20, suggestedMax: 40, title: { display: true, text: "°C" } }
            }
        }
    });

    // 3. Gráfico Sismográfico do MPU6050 (Estilo Otimizado)
    const seismoCanvas = document.getElementById("seismographChart");
    let seismographChart = null;

    if (seismoCanvas) {
        const seismoContext = seismoCanvas.getContext("2d");
        seismographChart = new Chart(seismoContext, {
            type: "line",
            data: {
                labels: [],
                datasets: [
                    {
                        label: "Eixo X (g)",
                        data: [],
                        borderColor: "#f1c40f", // Amarelo harmonizado
                        borderWidth: 1.5,
                        fill: false,
                        tension: 0.1
                    },
                    {
                        label: "Eixo Y (g)",
                        data: [],
                        borderColor: "#e74c3c", // Vermelho harmonizado
                        borderWidth: 1.5,
                        fill: false,
                        tension: 0.1
                    },
                    {
                        label: "Eixo Z (g)",
                        data: [],
                        borderColor: "#9b59b6", // Roxo / Magenta harmonizado
                        borderWidth: 1.5,
                        fill: false,
                        tension: 0.1
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                events: [], // Desabilita eventos de ponteiro/hover para economizar CPU
                elements: { point: { radius: 0 } },
                scales: {
                    x: {
                        grid: { color: "rgba(0, 0, 0, 0.05)" },
                        title: { display: true, text: "Tempo" }
                    },
                    y: {
                        suggestedMin: -2.0,
                        suggestedMax: 2.0,
                        grid: { color: "rgba(0, 0, 0, 0.05)" },
                        title: { display: true, text: "Aceleração (g)" }
                    }
                }
            }
        });
    }

    // Elementos DOM
    const connectionStatus = document.getElementById("connection-status");
    const bpmValue = document.getElementById("bpm-val");
    const averageBpmValue = document.getElementById("avg-bpm-val");
    const irValue = document.getElementById("ir-val");
    const temperatureValue = document.getElementById("temp-val");
    const temperatureStatus = document.getElementById("temp-status");
    const fingerBox = document.getElementById("finger-box");
    const fingerText = document.getElementById("finger-text");
    const lastUpdate = document.getElementById("last-update");

    const accelXVal = document.getElementById("accel-x-val");
    const accelYVal = document.getElementById("accel-y-val");
    const accelZVal = document.getElementById("accel-z-val");
    const accelMagVal = document.getElementById("accel-mag-val");
    const mpuSeismoStatus = document.getElementById("mpu-seismo-status");

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

    function updateHeartRateChart(telemetry) {
        if (!telemetry.last_update || telemetry.data_stale) return;

        const labels = heartRateChart.data.labels;
        if (labels.length > 0 && labels[labels.length - 1] === telemetry.last_update) return;

        if (labels.length >= maximumSamples) {
            labels.shift();
            heartRateChart.data.datasets.forEach((ds) => ds.data.shift());
        }

        labels.push(telemetry.last_update);
        heartRateChart.data.datasets[0].data.push(telemetry.bpm);
        heartRateChart.data.datasets[1].data.push(telemetry.avg_bpm);
        heartRateChart.update("none");
    }

    function updateTempChart(telemetry) {
        if (!telemetry.last_update || telemetry.data_stale) return;

        const labels = temperatureChart.data.labels;
        if (labels.length > 0 && labels[labels.length - 1] === telemetry.last_update) return;

        if (labels.length >= maximumSamples) {
            labels.shift();
            temperatureChart.data.datasets[0].data.shift();
        }

        labels.push(telemetry.last_update);
        const tempVal = (telemetry.temperature_valid && typeof telemetry.temperature_c === "number")
            ? telemetry.temperature_c
            : null;

        temperatureChart.data.datasets[0].data.push(tempVal);
        temperatureChart.update("none");
    }

    function updateSeismograph(telemetry) {
        if (!seismographChart) return;

        if (!telemetry.mpu_valid || !telemetry.accel) {
            if (mpuSeismoStatus) {
                mpuSeismoStatus.className = "status-badge offline";
                mpuSeismoStatus.innerText = "IMU Inativa";
            }
            if (accelXVal) accelXVal.innerText = "--";
            if (accelYVal) accelYVal.innerText = "--";
            if (accelZVal) accelZVal.innerText = "--";
            if (accelMagVal) accelMagVal.innerText = "--";
            return;
        }

        if (mpuSeismoStatus) {
            mpuSeismoStatus.className = "status-badge online";
            mpuSeismoStatus.innerText = "Ativo";
        }

        if (accelXVal) accelXVal.innerText = telemetry.accel.x.toFixed(2);
        if (accelYVal) accelYVal.innerText = telemetry.accel.y.toFixed(2);
        if (accelZVal) accelZVal.innerText = telemetry.accel.z.toFixed(2);
        if (accelMagVal) accelMagVal.innerText = (telemetry.accel_magnitude ?? 0).toFixed(2);

        const labels = seismographChart.data.labels;
        if (labels.length > 0 && labels[labels.length - 1] === telemetry.last_update) return;

        if (labels.length >= maximumSamples) {
            labels.shift();
            seismographChart.data.datasets.forEach((ds) => ds.data.shift());
        }

        labels.push(telemetry.last_update);
        seismographChart.data.datasets[0].data.push(telemetry.accel.x);
        seismographChart.data.datasets[1].data.push(telemetry.accel.y);
        seismographChart.data.datasets[2].data.push(telemetry.accel.z);

        seismographChart.update("none");
    }

    // Receptor SSE
    const eventSource = new EventSource("/chart-data");

    eventSource.onmessage = (event) => {
        const telemetry = JSON.parse(event.data);
        setConnectionState(telemetry);

        bpmValue.innerText = displayNumber(telemetry.bpm, 1);
        averageBpmValue.innerText = displayNumber(telemetry.avg_bpm);
        irValue.innerText = displayNumber(telemetry.ir);
        lastUpdate.innerText = telemetry.last_update ?? "--";

        if (telemetry.temperature_valid && typeof telemetry.temperature_c === "number") {
            temperatureValue.innerText = telemetry.temperature_c.toFixed(1);
            temperatureStatus.innerText = "Valid sensor reading";
        } else {
            temperatureValue.innerText = "--";
            temperatureStatus.innerText = "Temperature reading out of bounds";
        }

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

        updateHeartRateChart(telemetry);
        updateTempChart(telemetry);
        updateSeismograph(telemetry);
    };

    eventSource.onerror = () => {
        connectionStatus.className = "status-badge offline";
        connectionStatus.innerText = "Dashboard disconnected";
    };
});