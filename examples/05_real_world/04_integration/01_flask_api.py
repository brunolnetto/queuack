"""Flask API with background job processing.

# Difficulty: intermediate
"""

from flask import Flask, jsonify, request

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue

app = Flask(__name__)

db_path = create_temp_path("flask")
queue = DuckQueue(db_path)


def process_order(order_id: str, items: list):
    """Process order in background."""
    print(f"Processing order {order_id} with {len(items)} items...")
    # Simulate processing
    return {"order_id": order_id, "status": "completed"}


@app.route("/orders", methods=["POST"])
def create_order():
    """Create order and enqueue processing."""
    data = request.json
    order_id = data["order_id"]
    items = data["items"]

    # Enqueue background job
    job_id = queue.enqueue(process_order, args=(order_id, items), queue="orders")

    return jsonify({"order_id": order_id, "job_id": job_id, "status": "processing"})


@app.route("/jobs/", methods=["GET"])
def get_job_status(job_id):
    """Check job status."""
    job = queue.get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    return jsonify(
        {
            "job_id": job.id,
            "status": job.status,
            "created_at": job.created_at.isoformat(),
            "result": queue.get_result(job_id) if job.status == "done" else None,
        }
    )


# Start worker in separate process
if __name__ == "__main__":
    from multiprocessing import Process

    def run_worker():
        from queuack import Worker

        Worker(queue).run()

    worker_process = Process(target=run_worker, daemon=True)
    worker_process.start()

    app.run(debug=True)
