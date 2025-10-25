"""Command-line tool for queue management.

# Difficulty: intermediate
"""

import click
from tabulate import tabulate

from queuack import DuckQueue


@click.group()
@click.option("--db", default="queue.db", help="Database file")
@click.pass_context
def cli(ctx, db):
    """Queuack CLI - Manage your job queue."""
    ctx.ensure_object(dict)
    ctx.obj["queue"] = DuckQueue(db)


@cli.command()
@click.pass_context
def stats(ctx):
    """Show queue statistics."""
    queue = ctx.obj["queue"]
    stats = queue.stats()

    table = [[k.capitalize(), v] for k, v in stats.items()]
    print(tabulate(table, headers=["Status", "Count"], tablefmt="grid"))


@cli.command()
@click.option("--limit", default=10, help="Number of jobs to show")
@click.pass_context
def list_jobs(ctx, limit):
    """List recent jobs."""
    queue = ctx.obj["queue"]

    results = queue.conn.execute(f"""
        SELECT id, status, created_at, queue
        FROM jobs
        ORDER BY created_at DESC
        LIMIT {limit}
    """).fetchall()

    table = [[r[0][:8], r[1], r[2], r[3]] for r in results]
    print(
        tabulate(
            table, headers=["Job ID", "Status", "Created", "Queue"], tablefmt="grid"
        )
    )


@cli.command()
@click.argument("job_id")
@click.pass_context
def inspect(ctx, job_id):
    """Inspect a specific job."""
    queue = ctx.obj["queue"]
    job = queue.get_job(job_id)

    if not job:
        click.echo(f"Job {job_id} not found", err=True)
        return

    click.echo(f"\nJob: {job.id}")
    click.echo(f"Status: {job.status}")
    click.echo(f"Queue: {job.queue}")
    click.echo(f"Priority: {job.priority}")
    click.echo(f"Attempts: {job.attempts}/{job.max_attempts}")
    click.echo(f"Created: {job.created_at}")

    if job.error:
        click.echo(f"\nError:\n{job.error}")


@cli.command()
@click.option("--status", default="done", help="Status to purge")
@click.option("--hours", default=24, help="Older than hours")
@click.pass_context
def purge(ctx, status, hours):
    """Delete old jobs."""
    queue = ctx.obj["queue"]

    if click.confirm(f"Delete {status} jobs older than {hours}h?"):
        count = queue.purge(status=status, older_than_hours=hours)
        click.echo(f"✓ Deleted {count} jobs")


@cli.command()
@click.option("--concurrency", default=4, help="Worker threads")
@click.pass_context
def worker(ctx, concurrency):
    """Start a worker process."""
    queue = ctx.obj["queue"]

    from queuack import Worker

    click.echo(f"Starting worker (concurrency={concurrency})...")

    worker = Worker(queue, concurrency=concurrency)
    worker.run()


@cli.command()
@click.argument("dag_run_id")
@click.pass_context
def dag_status(ctx, dag_run_id):
    """Check DAG run status."""
    queue = ctx.obj["queue"]

    from queuack.dag import DAGRun

    dag_run = DAGRun(queue, dag_run_id)

    status = dag_run.get_status()
    progress = dag_run.get_progress()

    click.echo(f"\nDAG Run: {dag_run_id}")
    click.echo(f"Status: {status.value}")
    click.echo("\nProgress:")

    table = [[k.capitalize(), v] for k, v in progress.items()]
    print(tabulate(table, headers=["Status", "Count"], tablefmt="grid"))

    # List jobs
    jobs = dag_run.get_jobs()
    if jobs:
        click.echo("\nJobs:")
        job_table = [[j["name"], j["status"], j["completed_at"] or "N/A"] for j in jobs]
        print(
            tabulate(
                job_table, headers=["Name", "Status", "Completed"], tablefmt="grid"
            )
        )


if __name__ == "__main__":
    # Demo mode - create an illustrative demo with various job states
    import os
    import sys
    import time

    if len(sys.argv) == 1:
        # No arguments provided, run a demo
        print("🦆 Queuack CLI Demo - Job Queue in Action")
        print("=" * 50)

        # Create a temporary demo database
        demo_db = "demo_queue.db"

        # Clean up any existing demo database
        if os.path.exists(demo_db):
            os.remove(demo_db)

        print(f"Creating fresh demo database: {demo_db}")

        # Create queue and enqueue various jobs
        print(f"Using database: {demo_db}")
        queue = DuckQueue(demo_db)

        def success_task(name, duration=0.1):
            """A task that succeeds."""
            print(f"✅ Processing {name}")
            time.sleep(duration)
            return f"Completed {name}"

        def failing_task(name):
            """A task that fails."""
            print(f"❌ Failing {name}")
            raise Exception(f"Simulated failure in {name}")

        def slow_task(name):
            """A slow task that will remain pending."""
            print(f"⏳ Starting slow task {name}")
            time.sleep(10)  # Much slower than our demo timeout
            return f"Finally completed {name}"

        print("\n📝 Enqueueing demo jobs...")

        # Enqueue successful jobs
        for i in range(3):
            job_id = queue.enqueue(
                success_task, args=(f"success_job_{i + 1}",), queue="demo"
            )
            print(f"  ✅ Enqueued success_job_{i + 1}: {job_id[:8]}...")

        # Enqueue failing jobs
        for i in range(2):
            job_id = queue.enqueue(
                failing_task, args=(f"fail_job_{i + 1}",), queue="demo"
            )
            print(f"  ❌ Enqueued fail_job_{i + 1}: {job_id[:8]}...")

        # Enqueue slow jobs (will remain pending)
        for i in range(2):
            job_id = queue.enqueue(slow_task, args=(f"slow_job_{i + 1}",), queue="demo")
            print(f"  ⏳ Enqueued slow_job_{i + 1}: {job_id[:8]}...")

        # Force commit to ensure jobs are saved
        queue.conn.commit()
        print("  💾 Committed all jobs to database")
        stats = queue.stats(queue="demo")
        table = [[k.capitalize(), v] for k, v in stats.items()]
        print(tabulate(table, headers=["Status", "Count"], tablefmt="grid"))

        print("\n🏃 Starting worker for 3 seconds...")

        # Start worker in background for a short time
        import threading

        from queuack import Worker

        worker = Worker(queue, queues=["demo"], concurrency=2)

        def run_worker_briefly():
            start_time = time.perf_counter()
            job_count = 0
            while (
                time.perf_counter() - start_time < 3 and job_count < 10
            ):  # Run for 3 seconds or 10 jobs max
                job = worker._claim_next_job()
                if job:
                    job_count += 1
                    worker._execute_job(job, job_count)
                else:
                    time.sleep(0.1)

        worker_thread = threading.Thread(target=run_worker_briefly, daemon=True)
        worker_thread.start()
        worker_thread.join(timeout=3.5)

        print("\n📊 Final queue stats after worker run:")
        stats = queue.stats(queue="demo")
        table = [[k.capitalize(), v] for k, v in stats.items()]
        print(tabulate(table, headers=["Status", "Count"], tablefmt="grid"))

        print("\n📋 Recent jobs:")
        results = queue.conn.execute("""
            SELECT id, status, queue, created_at
            FROM jobs
            ORDER BY created_at DESC
            LIMIT 10
        """).fetchall()
        queue.conn.commit()

        job_table = [[r[0][:8], r[1], r[2], str(r[3])[:19]] for r in results]
        print(
            tabulate(
                job_table,
                headers=["Job ID", "Status", "Queue", "Created"],
                tablefmt="grid",
            )
        )

        print("\n🎯 Demo Summary:")
        print("• ✅ Success jobs: Completed successfully")
        print("• ❌ Failed jobs: Failed with retries exhausted")
        print("• ⏳ Slow jobs: Still pending (worker timeout)")
        print("• 📊 CLI shows real-time queue management")

        print(f"\n💡 Try: python {sys.argv[0]} --db {demo_db} inspect <job_id>")
        print(f"💡 Or: python {sys.argv[0]} --db {demo_db} worker")

    else:
        cli()
