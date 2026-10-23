document.addEventListener("DOMContentLoaded", () => {
    const maximumSamples = 30;

    // --- 1. Gráfico de Frequência Cardíaca (BPM / Média) ---
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

    // --- 2. Gráfico de Temperatura Corporal ---
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
                y: {
                    suggestedMin: 20,
                    suggestedMax: 40,
                    title: { display: true, text: "°C" }
                }
            }
        }
    });

    // --- 3. Gráfico Sismográfico de Aceleração (MPU6050 X, Y, Z) ---
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
                        borderColor: "#ffff00", // Amarelo
                        borderWidth: 1.5,
                        pointRadius: 0,
                        fill: false,
                        tension: 0.1
                    },
                    {
                        label: "Eixo Y (g)",
                        data: [],
                        borderColor: "#ff3333", // Vermelho
                        borderWidth: 1.5,
                        pointRadius: 0,
                        fill: false,
                        tension: 0.1
                    },
                    {
                        label: "Eixo Z (g)",
                        data: [],
                        borderColor: "#ff00ff", // Magenta
                        borderWidth: 1.5,
                        pointRadius: 0,
                        fill: false,
                        tension: 0.1
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                scales: {
                    x: {
                        grid: { color: "rgba(255, 255, 255, 0.15)" },
                        ticks: { color: "#888888" },
                        title: { display: true, text: "Tempo", color: "#aaaaaa" }
                    },
                    y: {
                        suggestedMin: -2.0,
                        suggestedMax: 2.0,
                        grid: { color: "rgba(255, 255, 255, 0.15)" },
                        ticks: { color: "#888888" },
                        title: { display: true, text: "Aceleração (g)", color: "#aaaaaa" }
                    }
                },
                plugins: {
                    legend: {
                        labels: { color: "#ffffff" }
                    }
                }
            }
        });
    }

    // Referências de Elementos do DOM
    const connectionStatus = document.getElementById("connection-status");
    const bpmValue = document.getElementById("bpm-val");
    const averageBpmValue = document.getElementById("avg-bpm-val");
    const irValue = document.getElementById("ir-val");
    const temperatureValue = document.getElementById("temp-val");
    const temperatureStatus = document.getElementById("temp-status");
    const fingerBox = document.getElementById("finger-box");
    const fingerText = document.getElementById("finger-text");
    const lastUpdate = document.getElementById("last-update");

    // Elementos DOM do Sismógrafo / MPU
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

    function updateTempChart(telemetry) {
        if (telemetry.last_update === null || telemetry.data_stale) return;

        const labels = temperatureChart.data.labels;

        if (labels.length > 0 && labels[labels.length - 1] === telemetry.last_update) {
            return;
        }

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
                mpuSeismoStatus.innerText = "IMU Inativa";
                mpuSeismoStatus.style.background = "#772222";
            }
            if (accelXVal) accelXVal.innerText = "--";
            if (accelYVal) accelYVal.innerText = "--";
            if (accelZVal) accelZVal.innerText = "--";
            if (accelMagVal) accelMagVal.innerText = "--";
            return;
        }

        if (mpuSeismoStatus) {
            mpuSeismoStatus.innerText = "Sismógrafo Ativo";
            mpuSeismoStatus.style.background = "#1b5e20";
        }

        // Atualização dos valores numéricos dos eixos
        if (accelXVal) accelXVal.innerText = telemetry.accel.x.toFixed(2);
        if (accelYVal) accelYVal.innerText = telemetry.accel.y.toFixed(2);
        if (accelZVal) accelZVal.innerText = telemetry.accel.z.toFixed(2);
        if (accelMagVal) accelMagVal.innerText = (telemetry.accel_magnitude ?? 0).toFixed(2);

        const labels = seismographChart.data.labels;

        if (labels.length > 0 && labels[labels.length - 1] === telemetry.last_update) {
            return;
        }

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

    // --- Receptor de Eventos SSE ---
    const eventSource = new EventSource("/chart-data");

    eventSource.onmessage = (event) => {
        const telemetry = JSON.parse(event.data);
        setConnectionState(telemetry);

        bpmValue.innerText = displayNumber(telemetry.bpm, 1);
        averageBpmValue.innerText = displayNumber(telemetry.avg_bpm);
        irValue.innerText = displayNumber(telemetry.ir);
        lastUpdate.innerText = telemetry.last_update ?? "--";

        // Atualização da Temperatura
        if (telemetry.temperature_valid && typeof telemetry.temperature_c === "number") {
            temperatureValue.innerText = telemetry.temperature_c.toFixed(1);
            temperatureStatus.innerText = "Valid sensor reading";
        } else {
            temperatureValue.innerText = "--";
            temperatureStatus.innerText = "Temperature reading out of bounds";
        }

        // Atualização do estado do Dedo
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

        // Atualização dos Gráficos
        updateHeartRateChart(telemetry);
        updateTempChart(telemetry);
        updateSeismograph(telemetry);
    };

    eventSource.onerror = () => {
        connectionStatus.className = "status-badge offline";
        connectionStatus.innerText = "Dashboard disconnected";
    };
});