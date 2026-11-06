document.addEventListener("DOMContentLoaded", () => {
    const maximumSamples = 20;
    document.querySelectorAll(".tab-btn").forEach(button => {
        button.addEventListener("click", event => switchTab(button.dataset.tab, event));
    });
    document.getElementById("refresh-logs").addEventListener("click", fetchLogHistory);

    function createChart(context, config) {
        try {
            if (typeof Chart !== "undefined") return new Chart(context, config);
        } catch (error) {
            console.error("Chart initialization failed", error);
        }
        document.getElementById("chart-status").hidden = false;
        return null;
    }

    // 1. Gráfico de Frequência Cardíaca
    const chartContext = document.getElementById("heartRateChart").getContext("2d");
    const heartRateChart = createChart(chartContext, {
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
    const temperatureChart = createChart(tempChartContext, {
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

    // 3. Gráfico Sismográfico do MPU6050
    const seismoCanvas = document.getElementById("seismographChart");
    let seismographChart = null;

    if (seismoCanvas) {
        const seismoContext = seismoCanvas.getContext("2d");
        seismographChart = createChart(seismoContext, {
            type: "line",
            data: {
                labels: [],
                datasets: [
                    {
                        label: "Eixo X (g)",
                        data: [],
                        borderColor: "#f1c40f",
                        borderWidth: 1.5,
                        fill: false,
                        tension: 0.1
                    },
                    {
                        label: "Eixo Y (g)",
                        data: [],
                        borderColor: "#e74c3c",
                        borderWidth: 1.5,
                        fill: false,
                        tension: 0.1
                    },
                    {
                        label: "Eixo Z (g)",
                        data: [],
                        borderColor: "#9b59b6",
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
                events: [],
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
        if (!heartRateChart || !telemetry.last_update || telemetry.data_stale || !telemetry.mqtt_connected) return;

        const labels = heartRateChart.data.labels;
        if (heartRateChart.lastSampleId === telemetry.sample_id) return;
        heartRateChart.lastSampleId = telemetry.sample_id;

        if (labels.length >= maximumSamples) {
            labels.shift();
            heartRateChart.data.datasets.forEach((ds) => ds.data.shift());
        }

        labels.push(telemetry.last_update);
        heartRateChart.data.datasets[0].data.push(telemetry.heart_rate_valid ? telemetry.bpm : null);
        heartRateChart.data.datasets[1].data.push(telemetry.heart_rate_valid ? telemetry.avg_bpm : null);
        heartRateChart.update("none");
    }

    function updateTempChart(telemetry) {
        if (!temperatureChart || !telemetry.last_update || telemetry.data_stale || !telemetry.mqtt_connected) return;

        const labels = temperatureChart.data.labels;
        if (temperatureChart.lastSampleId === telemetry.sample_id) return;
        temperatureChart.lastSampleId = telemetry.sample_id;

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
        if (!telemetry.mqtt_connected || telemetry.data_stale || !telemetry.mpu_valid || !telemetry.accel_batch || telemetry.accel_batch.length === 0) {
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
            if (telemetry.fall_state === "WAITING_CONFIRMATION" || telemetry.fall_state === "FULL_ALERT") {
                mpuSeismoStatus.className = "status-badge offline";
                mpuSeismoStatus.innerText = `FALL DETECTED! (${telemetry.min_g_dip}g)`;
            } else {
                mpuSeismoStatus.className = "status-badge online";
                mpuSeismoStatus.innerText = "IMU ativa";
            }
        }

        // Display the latest sample's numerical readouts from the batch
        const lastSample = telemetry.accel_batch[telemetry.accel_batch.length - 1];
        if (lastSample && lastSample.length >= 4) {
            if (accelXVal) accelXVal.innerText = lastSample[0].toFixed(2);
            if (accelYVal) accelYVal.innerText = lastSample[1].toFixed(2);
            if (accelZVal) accelZVal.innerText = lastSample[2].toFixed(2);
            if (accelMagVal) accelMagVal.innerText = lastSample[3].toFixed(2);
        }

        // SSE repeats snapshots; append each acquired batch only once.
        if (!seismographChart || seismographChart.lastSampleId === telemetry.sample_id) return;
        seismographChart.lastSampleId = telemetry.sample_id;
        telemetry.accel_batch.forEach((sample) => {
            if (seismographChart.data.labels.length >= 100) {
                seismographChart.data.labels.shift();
                seismographChart.data.datasets.forEach((ds) => ds.data.shift());
            }

            seismographChart.data.labels.push("");
            seismographChart.data.datasets[0].data.push(sample[0]); // X
            seismographChart.data.datasets[1].data.push(sample[1]); // Y
            seismographChart.data.datasets[2].data.push(sample[2]); // Z
        });

        seismographChart.update("none");
    }

    function updateFallAlertState(telemetry) {
        const alertBanner = document.getElementById("fall-alert-banner");
        if (!alertBanner) return;

        if (telemetry.fall_state === "WAITING_CONFIRMATION") {
            alertBanner.className = "alert-box alert-warning";
            alertBanner.innerHTML = "<strong>WAITING CONFIRMATION:</strong> Fall detected! Press LED button on wearable to cancel false alarm.";
            alertBanner.style.display = "block";
        } else if (telemetry.fall_state === "FULL_ALERT") {
            alertBanner.className = "alert-box alert-danger";
            alertBanner.innerHTML = "<strong>FALL ALERT:</strong> No cancellation received. Check on the wearer.";
            alertBanner.style.display = "block";
        } else {
            alertBanner.style.display = "none";
        }
    }

    // Receptor SSE
    const eventSource = new EventSource("/chart-data");

    eventSource.onmessage = (event) => {
        const telemetry = JSON.parse(event.data);
        setConnectionState(telemetry);
        const fresh = telemetry.mqtt_connected && !telemetry.data_stale;
        document.getElementById("log-status").hidden = !telemetry.log_error;

        bpmValue.innerText = fresh && telemetry.heart_rate_valid ? displayNumber(telemetry.bpm, 1) : "--";
        averageBpmValue.innerText = fresh && telemetry.heart_rate_valid ? displayNumber(telemetry.avg_bpm) : "--";
        irValue.innerText = fresh ? displayNumber(telemetry.ir) : "--";
        lastUpdate.innerText = telemetry.last_update ?? "--";

        if (fresh && telemetry.temperature_valid && typeof telemetry.temperature_c === "number") {
            temperatureValue.innerText = telemetry.temperature_c.toFixed(1);
            temperatureStatus.innerText = "Valid sensor reading";
        } else {
            temperatureValue.innerText = "--";
            temperatureStatus.innerText = fresh ? "Temperature reading out of bounds" : "Waiting for fresh telemetry";
        }

        if (telemetry.last_update === null) {
            fingerBox.className = "alert-box alert-warning";
            fingerText.innerText = "Waiting for data";
        } else if (!fresh) {
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
        updateFallAlertState(telemetry); // Chamada movida para dentro do evento SSE
    };

    eventSource.onerror = () => {
        connectionStatus.className = "status-badge offline";
        connectionStatus.innerText = "Dashboard disconnected";
        [bpmValue, averageBpmValue, irValue, temperatureValue, accelXVal, accelYVal, accelZVal, accelMagVal].forEach(el => {
            if (el) el.innerText = "--";
        });
        fingerText.innerText = "Waiting for fresh telemetry";
        fingerBox.className = "alert-box alert-warning";
        temperatureStatus.innerText = "Waiting for fresh telemetry";
        if (mpuSeismoStatus) {
            mpuSeismoStatus.className = "status-badge offline";
            mpuSeismoStatus.innerText = "IMU sem dados atuais";
        }
    };

    function switchTab(tabId, event) {
        document.querySelectorAll(".tab-content").forEach(el => el.style.display = "none");
        document.querySelectorAll(".tab-btn").forEach(el => el.classList.remove("active"));

        document.getElementById(tabId).style.display = "block";
        if (event && event.currentTarget) {
            event.currentTarget.classList.add("active");
        }

        if (tabId === "logs-tab") {
            fetchLogHistory();
        } else {
            [heartRateChart, temperatureChart, seismographChart].forEach(chart => chart?.resize());
        }
    }

    function fetchLogHistory() {
        const tableBody = document.getElementById("log-table-body");
        if (!tableBody) return;

        fetch("/api/logs")
            .then(response => {
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                return response.json();
            })
            .then(data => {
                if (!data || data.length === 0) {
                    tableBody.innerHTML = `<tr><td style="padding: 10px; text-align: center;">No log records found.</td></tr>`;
                    return;
                }

                tableBody.replaceChildren();
                data.forEach(item => {
                    const row = document.createElement("tr");
                    const cell = document.createElement("td");
                    cell.textContent = item.raw;
                    row.appendChild(cell);
                    tableBody.appendChild(row);
                });
            })
            .catch(err => {
                console.error("Error loading log file:", err);
                tableBody.innerHTML = `<tr><td style="padding: 10px; color: red;">Failed to load log history.</td></tr>`;
            });
    }

});
