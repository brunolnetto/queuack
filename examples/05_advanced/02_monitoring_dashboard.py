"""Flask-based monitoring dashboard PoC for Queuack queues.

This is a proof-of-concept Flask application that provides a persistent web UI
for monitoring queue performance. It demonstrates how to integrate Queuack
monitoring into a web application.

# Difficulty: advanced

Key Concepts:
- Flask web application: Building monitoring UIs with web frameworks
- REST API endpoints: Exposing queue metrics via HTTP APIs
- Real-time updates: Polling-based updates for dashboard refresh
- Chart.js integration: Client-side visualization of metrics
- Persistent monitoring: Long-running web service for queue oversight
"""

import os
import random
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Dict, List

from flask import Flask, jsonify, render_template
from flask_socketio import SocketIO, emit

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue, Worker


class MetricsCollector:
    """Collects and analyzes queue performance metrics."""

    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.metrics_history: deque = deque(maxlen=max_history)
        self.alerts: List[Dict[str, Any]] = []
        self.alert_thresholds = {
            "pending_jobs": 50,
            "failed_jobs": 10,
            "avg_processing_time": 30.0,  # seconds
            "error_rate": 0.1,  # 10%
        }

    def record_metrics(
        self, queue_stats: Dict[str, Any], processing_times: List[float]
    ):
        """Record current metrics snapshot."""
        timestamp = datetime.now()

        metrics = {
            "timestamp": timestamp.isoformat(),
            "queue_stats": queue_stats,
            "processing_times": processing_times,
            "avg_processing_time": sum(processing_times) / len(processing_times)
            if processing_times
            else 0,
            "error_rate": queue_stats["failed"]
            / max(queue_stats["done"] + queue_stats["failed"], 1),
            "throughput": len(processing_times) / 60.0,  # jobs per minute
        }

        self.metrics_history.append(metrics)
        self._check_alerts(metrics)

        return metrics

    def _check_alerts(self, metrics: Dict[str, Any]):
        """Check for alert conditions and create alerts."""
        alerts = []

        if metrics["queue_stats"]["pending"] > self.alert_thresholds["pending_jobs"]:
            alerts.append(
                {
                    "type": "warning",
                    "message": f"High pending jobs: {metrics['queue_stats']['pending']}",
                    "timestamp": metrics["timestamp"],
                }
            )

        if metrics["queue_stats"]["failed"] > self.alert_thresholds["failed_jobs"]:
            alerts.append(
                {
                    "type": "error",
                    "message": f"High failed jobs: {metrics['queue_stats']['failed']}",
                    "timestamp": metrics["timestamp"],
                }
            )

        if (
            metrics["avg_processing_time"]
            > self.alert_thresholds["avg_processing_time"]
        ):
            alerts.append(
                {
                    "type": "warning",
                    "message": f"Slow processing: {metrics['avg_processing_time']:.1f}s avg",
                    "timestamp": metrics["timestamp"],
                }
            )

        if metrics["error_rate"] > self.alert_thresholds["error_rate"]:
            alerts.append(
                {
                    "type": "error",
                    "message": f"High error rate: {metrics['error_rate']:.1%}",
                    "timestamp": metrics["timestamp"],
                }
            )

        self.alerts.extend(alerts)
        # Keep only recent alerts
        if len(self.alerts) > 100:
            self.alerts = self.alerts[-100:]

    def get_recent_metrics(self, hours: int = 1) -> List[Dict[str, Any]]:
        """Get metrics from the last N hours."""
        cutoff = datetime.now() - timedelta(hours=hours)
        return [
            m
            for m in self.metrics_history
            if datetime.fromisoformat(m["timestamp"]) > cutoff
        ]

    def get_summary_stats(self) -> Dict[str, Any]:
        """Get summary statistics from recent metrics."""
        recent = self.get_recent_metrics(1)
        if not recent:
            return {}

        return {
            "total_jobs_processed": sum(m["queue_stats"]["done"] for m in recent),
            "avg_throughput": sum(m["throughput"] for m in recent) / len(recent),
            "avg_processing_time": sum(m["avg_processing_time"] for m in recent)
            / len(recent),
            "max_pending": max(m["queue_stats"]["pending"] for m in recent),
            "total_alerts": len(
                [
                    a
                    for a in self.alerts
                    if datetime.fromisoformat(a["timestamp"])
                    > datetime.now() - timedelta(hours=1)
                ]
            ),
        }


# Global state for the Flask app
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Global variables (in a real app, use proper state management)
collector = None
queue = None
dashboard_thread = None
running = False


@app.route("/")
def dashboard():
    """Serve the main dashboard page."""
    return render_template("dashboard.html")


@app.route("/api/metrics")
def get_metrics():
    """API endpoint for current metrics."""
    if not collector:
        return jsonify({"error": "Collector not initialized"}), 500

    metrics = collector.get_recent_metrics(1)
    current = metrics[-1] if metrics else {}
    summary = collector.get_summary_stats()

    data = {
        "current_metrics": current,
        "summary": summary,
        "history": metrics[-50:],  # Last 50 data points
        "alerts": collector.alerts[-10:],  # Last 10 alerts
    }

    return jsonify(data)


@app.route("/api/alerts")
def get_alerts():
    """API endpoint for alerts."""
    if not collector:
        return jsonify({"error": "Collector not initialized"}), 500

    return jsonify(collector.alerts[-20:])


@socketio.on("connect")
def handle_connect():
    """Handle WebSocket connection."""
    print("Client connected")
    emit("status", {"message": "Connected to monitoring dashboard"})


@socketio.on("disconnect")
def handle_disconnect():
    """Handle WebSocket disconnection."""
    print("Client disconnected")


def simulate_workload():
    """Simulate realistic workload with varying patterns."""
    global collector, queue, running

    processing_times = []

    # Simulate workload patterns
    job_counter = 0
    while running:
        # Vary enqueue rate based on time of day (simulate business hours)
        hour = datetime.now().hour
        if 9 <= hour <= 17:  # Business hours
            jobs_per_batch = random.randint(5, 15)
        elif 18 <= hour <= 22:  # Evening
            jobs_per_batch = random.randint(2, 8)
        else:  # Off hours
            jobs_per_batch = random.randint(0, 3)

        # Enqueue jobs; sample processing times locally for metrics (approximate)
        for _ in range(jobs_per_batch):
            # Choose a job type for sampling
            job_type = random.choice(["fast", "medium", "slow", "error"])
            if job_type == "fast":
                sampled_time = random.uniform(0.1, 0.5)
            elif job_type == "medium":
                sampled_time = random.uniform(1.0, 3.0)
            elif job_type == "slow":
                sampled_time = random.uniform(5.0, 10.0)
            else:
                sampled_time = random.uniform(0.5, 2.0)

            try:
                # Enqueue the top-level, picklable job implementation
                queue.enqueue(
                    process_job_impl, args=(job_counter,), check_backpressure=True
                )
                processing_times.append(sampled_time)
                job_counter += 1
            except Exception as e:
                print(f"⚠️  Failed to enqueue job: {e}")

        # Record metrics and broadcast update
        stats = queue.stats()
        metrics = collector.record_metrics(stats, processing_times.copy())

        # Emit real-time update via WebSocket
        socketio.emit(
            "metrics_update",
            {
                "current_metrics": metrics,
                "summary": collector.get_summary_stats(),
                "history": collector.get_recent_metrics(1),
                "alerts": collector.alerts[-10:],
            },
        )

        time.sleep(5)  # Update every 5 seconds


def process_job_impl(job_id: int):
    """Top-level worker job implementation (picklable)."""
    start_time = time.time()
    job_type = random.choice(["fast", "medium", "slow", "error"])
    if job_type == "fast":
        time.sleep(random.uniform(0.1, 0.5))
    elif job_type == "medium":
        time.sleep(random.uniform(1.0, 3.0))
    elif job_type == "slow":
        time.sleep(random.uniform(2.0, 5.0))
    else:
        time.sleep(random.uniform(0.1, 0.5))
        raise Exception(f"Simulated error in job {job_id}")

    processing_time = time.time() - start_time
    return f"Job {job_id} completed in {processing_time:.2f}s"


def run_workers(num_workers: int = 3):
    """Run multiple worker processes."""
    workers = []
    for i in range(num_workers):
        worker = Worker(queue, worker_id=f"worker-{i}", concurrency=2)
        worker_thread = threading.Thread(target=worker.run, daemon=True)
        worker_thread.start()
        workers.append(worker_thread)

    return workers


def create_templates():
    """Create the HTML template for the dashboard."""
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    os.makedirs(template_dir, exist_ok=True)

    dashboard_html = """
<!DOCTYPE html>
<html>
<head>
    <title>Queuack Flask Monitoring Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 20px; }
        .metric-card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .metric-value { font-size: 2em; font-weight: bold; color: #007bff; }
        .alerts { background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .alert { padding: 10px; margin: 5px 0; border-radius: 4px; }
        .alert-warning { background: #fff3cd; border: 1px solid #ffeaa7; }
        .alert-error { background: #f8d7da; border: 1px solid #f5c6cb; }
        .chart-container { background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        canvas { max-width: 100%; }
        .status { background: white; padding: 10px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Queuack Flask Monitoring Dashboard</h1>
            <p>Real-time queue monitoring and performance analytics (Flask PoC)</p>
            <div id="last-update">Last update: <span id="update-time">-</span></div>
        </div>

        <div class="status">
            <strong>Status:</strong> <span id="connection-status">Connecting...</span>
        </div>

        <div class="metrics-grid" id="metrics-grid">
            <!-- Metrics will be populated by JavaScript -->
        </div>

        <div class="alerts">
            <h2>🚨 Recent Alerts</h2>
            <div id="alerts-container">
                <p>No recent alerts</p>
            </div>
        </div>

        <div class="chart-container">
            <h2>📈 Queue Performance (Last Hour)</h2>
            <canvas id="performanceChart" width="400" height="200"></canvas>
        </div>

        <div class="chart-container">
            <h2>⚡ Throughput Trends</h2>
            <canvas id="throughputChart" width="400" height="200"></canvas>
        </div>
    </div>

    <script>
        const socket = io();
        let performanceChart, throughputChart;

        socket.on('connect', function() {
            document.getElementById('connection-status').textContent = 'Connected';
            document.getElementById('connection-status').style.color = 'green';
        });

        socket.on('disconnect', function() {
            document.getElementById('connection-status').textContent = 'Disconnected';
            document.getElementById('connection-status').style.color = 'red';
        });

        socket.on('metrics_update', function(data) {
            updateDashboard(data);
        });

        socket.on('status', function(data) {
            console.log('Status:', data.message);
        });

        function updateDashboard(data) {
            document.getElementById('update-time').textContent = new Date().toLocaleTimeString();

            // Update metrics
            const grid = document.getElementById('metrics-grid');
            grid.innerHTML = '';

            if (data.current_metrics && data.current_metrics.queue_stats) {
                Object.entries(data.current_metrics.queue_stats).forEach(([key, value]) => {
                    const card = document.createElement('div');
                    card.className = 'metric-card';
                    card.innerHTML = `
                        <h3>${key.charAt(0).toUpperCase() + key.slice(1)} Jobs</h3>
                        <div class="metric-value">${value}</div>
                    `;
                    grid.appendChild(card);
                });

                // Add processing metrics
                const processingCard = document.createElement('div');
                processingCard.className = 'metric-card';
                processingCard.innerHTML = `
                    <h3>Avg Processing Time</h3>
                    <div class="metric-value">${data.current_metrics.avg_processing_time.toFixed(1)}s</div>
                `;
                grid.appendChild(processingCard);

                const throughputCard = document.createElement('div');
                throughputCard.className = 'metric-card';
                throughputCard.innerHTML = `
                    <h3>Throughput</h3>
                    <div class="metric-value">${data.current_metrics.throughput.toFixed(1)}/min</div>
                `;
                grid.appendChild(throughputCard);
            }

            // Update alerts
            const alertsContainer = document.getElementById('alerts-container');
            if (data.alerts && data.alerts.length > 0) {
                alertsContainer.innerHTML = data.alerts.slice(-5).map(alert => `
                    <div class="alert alert-${alert.type}">
                        <strong>${alert.type.toUpperCase()}:</strong> ${alert.message}
                        <small>(${new Date(alert.timestamp).toLocaleTimeString()})</small>
                    </div>
                `).join('');
            }

            // Update charts
            updateCharts(data.history);
        }

        function updateCharts(history) {
            if (!history || history.length === 0) return;

            const labels = history.map(h => new Date(h.timestamp).toLocaleTimeString());
            const pending = history.map(h => h.queue_stats.pending);
            const throughput = history.map(h => h.throughput);

            if (!performanceChart) {
                const ctx1 = document.getElementById('performanceChart').getContext('2d');
                performanceChart = new Chart(ctx1, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Pending Jobs',
                            data: pending,
                            borderColor: 'rgb(75, 192, 192)',
                            tension: 0.1
                        }]
                    },
                    options: {
                        responsive: true,
                        scales: {
                            y: { beginAtZero: true }
                        }
                    }
                });
            } else {
                performanceChart.data.labels = labels;
                performanceChart.data.datasets[0].data = pending;
                performanceChart.update();
            }

            if (!throughputChart) {
                const ctx2 = document.getElementById('throughputChart').getContext('2d');
                throughputChart = new Chart(ctx2, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Jobs/Minute',
                            data: throughput,
                            borderColor: 'rgb(255, 99, 132)',
                            tension: 0.1
                        }]
                    },
                    options: {
                        responsive: true,
                        scales: {
                            y: { beginAtZero: true }
                        }
                    }
                });
            } else {
                throughputChart.data.labels = labels;
                throughputChart.data.datasets[0].data = throughput;
                throughputChart.update();
            }
        }

        // Initial load
        fetch('/api/metrics')
            .then(r => r.json())
            .then(data => updateDashboard(data))
            .catch(err => console.error('Failed to load initial metrics:', err));
    </script>
</body>
</html>
    """

    with open(os.path.join(template_dir, "dashboard.html"), "w") as f:
        f.write(dashboard_html)


# Main execution
if __name__ == "__main__":
    print("🚀 Starting Queuack Flask Monitoring Dashboard...")

    # Create templates
    create_templates()

    # Create queue and collector
    db_path = create_temp_path("flask_monitoring")
    queue = DuckQueue(db_path)
    collector = MetricsCollector()

    # Start workers
    print("👷 Starting worker processes...")
    workers = run_workers(num_workers=3)

    # Start workload simulation
    print("📊 Starting workload simulation...")
    running = True
    workload_thread = threading.Thread(target=simulate_workload, daemon=True)
    workload_thread.start()

    print("\n" + "=" * 60)
    print("🎯 Flask Monitoring Dashboard is running!")
    print("=" * 60)
    print("📱 Open your browser to: http://localhost:5000")
    print("📊 Real-time metrics and charts")
    print("🚨 Alert system for queue health")
    print("📈 Historical trend analysis")
    print("🔄 WebSocket updates for live data")
    print("\nPress Ctrl+C to stop...")
    print("=" * 60)

    try:
        # Run the Flask app with SocketIO
        socketio.run(app, host="0.0.0.0", port=5000, debug=False)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down Flask dashboard...")
        running = False
        print("✅ Dashboard stopped.")
