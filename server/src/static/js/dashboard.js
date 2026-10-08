document.addEventListener("DOMContentLoaded", () => {
    // 1. Initialize Chart.js for Heart Rate & SpO2 Trends
    const ctx = document.getElementById("ppgChart").getContext("2d");
    const ppgChart = new Chart(ctx, {
        type: "line",
        data: {
            labels: [], // Time labels
            datasets: [
                {
                    label: "Heart Rate (BPM)",
                    data: [],
                    borderColor: "#e74c3c",
                    borderWidth: 2,
                    fill: false,
                    tension: 0.3
                },
                {
                    label: "SpO2 (%)",
                    data: [],
                    borderColor: "#3498db",
                    borderWidth: 2,
                    fill: false,
                    tension: 0.3
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { display: true, title: { display: true, text: 'Time' } },
                y: { beginAtZero: false }
            }
        }
    });

    // 2. Connect to Flask SSE endpoint
    const eventSource = new EventSource("/chart-data");

    eventSource.onmessage = function (event) {
        const telemetry = JSON.parse(event.data);

        // Update Text Metrics
        if (telemetry.hr !== undefined) document.getElementById("hr-val").innerText = telemetry.hr;
        if (telemetry.spo2 !== undefined) document.getElementById("spo2-val").innerText = telemetry.spo2;
        if (telemetry.temp !== undefined) document.getElementById("temp-val").innerText = telemetry.temp.toFixed(1);

        // Handle Alert Status (e.g., Fall Detected / Warning)
        const alertBox = document.getElementById("alert-box");
        const alertText = document.getElementById("alert-text");

        if (telemetry.fall_alert) {
            alertBox.className = "alert-box alert-danger";
            alertText.innerText = "POSSIBLE FALL DETECTED!";
        } else {
            alertBox.className = "alert-box alert-normal";
            alertText.innerText = "System Normal";
        }

        // Update Chart Data (Keep last 20 samples)
        const timeLabel = telemetry.time;

        if (ppgChart.data.labels.length >= 20) {
            ppgChart.data.labels.shift();
            ppgChart.data.datasets[0].data.shift();
            ppgChart.data.datasets[1].data.shift();
        }

        ppgChart.data.labels.push(timeLabel);
        ppgChart.data.datasets[0].data.push(telemetry.hr);
        ppgChart.data.datasets[1].data.push(telemetry.spo2);

        ppgChart.update("quiet");
    };

    eventSource.onerror = function () {
        const statusBadge = document.getElementById("connection-status");
        statusBadge.className = "status-badge offline";
        statusBadge.innerText = "Disconnected";
    };
});