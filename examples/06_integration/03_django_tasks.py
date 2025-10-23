"""Django background tasks using Queuack.

# Difficulty: intermediate
"""

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue, Worker

# In your Django app
db_path = create_temp_path("django_queue")
queue = DuckQueue(db_path)


# tasks.py
def send_email_task(user_id, template):
    """Send email to user."""
    print(f"Sending email to user {user_id} with template '{template}'")
    # In real Django: from myapp.models import User
    # user = User.objects.get(id=user_id)
    # Send email...
    return f"Email sent to user {user_id}"


# views.py example
def signup_view_simulation():
    """Simulate a Django view that enqueues background tasks."""
    print("Simulating user signup...")

    # Simulate creating a user
    user_id = 123

    # Enqueue welcome email
    job_id = queue.enqueue(send_email_task, args=(user_id, "welcome"), queue="emails")

    print(f"✅ Enqueued welcome email job: {job_id}")
    return job_id


# management/commands/run_worker.py
class MockDjangoCommand:
    """Mock Django management command."""

    def __init__(self):
        self.stdout = type("MockStdout", (), {"write": lambda x: print(x.rstrip())})()

    def handle(self, *args, **options):
        worker = Worker(queue, concurrency=4)
        self.stdout.write("Starting Queuack worker...")
        print("Worker would run here (simulated)")
        # In real Django: worker.run()


if __name__ == "__main__":
    print("🦆 Django Integration Demo")
    print("=" * 40)

    # Simulate signup process
    job_id = signup_view_simulation()

    # Show job status
    job = queue.get_job(job_id)
    print(f"Job status: {job.status}")

    print("\n✅ Django integration example completed!")
    print("In a real Django app:")
    print("- tasks.py would contain your background functions")
    print("- views.py would enqueue jobs using queue.enqueue()")
    print("- management/commands/ would contain worker commands")
