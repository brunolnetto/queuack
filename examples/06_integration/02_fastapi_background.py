"""FastAPI with async background tasks.

# Difficulty: intermediate
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue

db_path = create_temp_path("fastapi")
queue = DuckQueue(db_path)


# Start worker with FastAPI
@asynccontextmanager
async def lifespan(app_: FastAPI):
    """Start background workers."""
    queue.start_workers(num_workers=2, concurrency=4)
    yield
    queue.stop_workers()


app = FastAPI(lifespan=lifespan)


def send_notification(user_id: str, message: str):
    """Send notification in background."""
    print(f"Sending to user {user_id}: {message}")


@app.post("/notifications")
async def create_notification(user_id: str, message: str):
    """Enqueue notification."""
    job_id = queue.enqueue(
        send_notification,
        args=(user_id, message),
        queue="notifications",
        priority=80,  # High priority
    )

    return {"job_id": job_id, "status": "enqueued"}


@app.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Check job status."""
    job = queue.get_job(job_id)
    if not job:
        return {"error": "Job not found"}

    return {
        "job_id": job.id,
        "status": job.status,
        "created_at": job.created_at.isoformat(),
        "result": queue.get_result(job_id) if job.status == "done" else None,
    }


if __name__ == "__main__":
    import socket

    import uvicorn

    # Find an available port
    sock = socket.socket()
    sock.bind(("", 0))
    port = sock.getsockname()[1]
    sock.close()

    print(f"Starting FastAPI server on port {port}")
    uvicorn.run(app, host="127.0.0.1", port=port)
