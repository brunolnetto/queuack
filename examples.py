import time

from queuack.core import DuckQueue, Worker, BackpressureError

# ============================================================================
# Example Usage
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("DUCKQUEUE DEMO: Multi-Queue, Multi-Worker with Backpressure")
    print("=" * 80)
    
    # Initialize queue
    queue = DuckQueue(":memory:")
    
    # Define example jobs for different queues
    def send_email(to, subject):
        """High-priority email job."""
        time.sleep(0.1)
        return f"Email sent to {to}"
    
    def process_report(report_id):
        """Medium-priority report job."""
        time.sleep(0.5)
        return f"Report {report_id} processed"
    
    def cleanup_logs(days):
        """Low-priority cleanup job."""
        time.sleep(0.2)
        return f"Cleaned logs older than {days} days"
    
    def slow_job(duration):
        """Simulate slow job."""
        time.sleep(duration)
        return f"Slept for {duration}s"
    
    # Scenario 1: Multi-queue with priorities
    print("\n--- SCENARIO 1: Multi-Queue Priority ---")
    
    # Enqueue jobs to different queues
    queue.enqueue(send_email, args=('user1@example.com', 'Welcome'), queue='emails', priority=90)
    queue.enqueue(send_email, args=('user2@example.com', 'Welcome'), queue='emails', priority=90)
    queue.enqueue(process_report, args=(101,), queue='reports', priority=50)
    queue.enqueue(process_report, args=(102,), queue='reports', priority=50)
    queue.enqueue(cleanup_logs, args=(30,), queue='maintenance', priority=10)
    
    print(f"Emails queue: {queue.stats('emails')}")
    print(f"Reports queue: {queue.stats('reports')}")
    print(f"Maintenance queue: {queue.stats('maintenance')}")
    
    # Worker listens to all queues, but prioritizes emails > reports > maintenance
    print("\nStarting worker with queue priorities...")
    worker = Worker(
        queue,
        queues=[
            ('emails', 100),      # Highest priority
            ('reports', 50),      # Medium priority
            ('maintenance', 10)   # Lowest priority
        ],
        concurrency=2,
        max_jobs_in_flight=4
    )
    
    # Simulate worker processing for 3 seconds
    import threading
    def stop_worker():
        time.sleep(3)
        worker.should_stop = True
    
    threading.Thread(target=stop_worker, daemon=True).start()
    worker.run(poll_interval=0.1)
    
    print("\nAfter processing:")
    print(f"Emails queue: {queue.stats('emails')}")
    print(f"Reports queue: {queue.stats('reports')}")
    print(f"Maintenance queue: {queue.stats('maintenance')}")
    
    # Scenario 2: Backpressure demonstration
    print("\n--- SCENARIO 2: Backpressure Protection ---")
    
    # Try to enqueue many jobs
    print("Enqueueing 15 slow jobs...")
    try:
        for i in range(15):
            queue.enqueue(
                slow_job,
                args=(2,),
                queue='slow',
                check_backpressure=False  # Disable for demo
            )
        print(f"Slow queue depth: {queue.stats('slow')['pending']} jobs")
        
        # Now try with backpressure enabled (would fail with 10000+ jobs)
        print("\nAttempting to enqueue with backpressure check...")
        queue.enqueue(slow_job, args=(1,), queue='slow', check_backpressure=True)
        print("✓ Enqueue succeeded (queue depth acceptable)")
        
    except BackpressureError as e:
        print(f"✗ Backpressure triggered: {e}")
    
    # Scenario 3: Multiple workers, single queue
    print("\n--- SCENARIO 3: Multiple Workers (Horizontal Scaling) ---")
    
    # Clear previous jobs
    queue.purge(queue='default', status='done', older_than_hours=0)
    
    # Enqueue batch of jobs
    print("Enqueueing 10 jobs...")
    for i in range(10):
        queue.enqueue(process_report, args=(i,), queue='default')
    
    print(f"Queue depth: {queue.stats('default')['pending']} jobs")
    
    # Start 3 workers concurrently
    print("\nStarting 3 workers to process jobs...")
    
    workers = []
    for i in range(3):
        w = Worker(
            queue,
            queues=['default'],
            worker_id=f"worker-{i}",
            concurrency=2
        )
        workers.append(w)
    
    # Run workers in threads
    def run_worker(w):
        # Auto-stop when queue empty
        empty_polls = 0
        while empty_polls < 3:
            job = queue.claim(queue='default', worker_id=w.worker_id)
            if job:
                empty_polls = 0
                w._execute_job(job, 1)
            else:
                empty_polls += 1
                time.sleep(0.1)
    
    threads = []
    for w in workers:
        t = threading.Thread(target=run_worker, args=(w,), daemon=True)
        t.start()
        threads.append(t)
    
    # Wait for workers
    for t in threads:
        t.join(timeout=5)
    
    print(f"\nFinal queue stats: {queue.stats('default')}")
    
    # Scenario 4: Real-world pattern (producer-consumer)
    print("\n--- SCENARIO 4: Producer-Consumer Pattern ---")
    print("Producer enqueues at 10 jobs/sec, Worker processes at 5 jobs/sec")
    print("Demonstrates queue buildup and backpressure...")
    
    queue.purge(queue='stream', status='done', older_than_hours=0)
    
    # Producer thread
    def producer():
        for i in range(20):
            try:
                queue.enqueue(
                    process_report,
                    args=(i,),
                    queue='stream',
                    check_backpressure=True
                )
                time.sleep(0.1)  # 10 jobs/sec
            except BackpressureError:
                print("  [Producer] Backpressure hit, slowing down...")
                time.sleep(1)
    
    # Consumer thread
    def consumer():
        w = Worker(queue, queues=['stream'], concurrency=1)
        for _ in range(10):  # Process 10 jobs
            job = queue.claim(queue='stream', worker_id='consumer-1')
            if job:
                w._execute_job(job, 1)
            time.sleep(0.2)  # 5 jobs/sec
    
    prod_thread = threading.Thread(target=producer, daemon=True)
    cons_thread = threading.Thread(target=consumer, daemon=True)
    
    prod_thread.start()
    time.sleep(0.5)  # Let producer get ahead
    cons_thread.start()
    
    prod_thread.join()
    cons_thread.join()
    
    final_stats = queue.stats('stream')
    print(f"\nFinal stats: {final_stats}")
    print("  Produced: 20 jobs")
    print("  Consumed: ~10 jobs")
    print(f"  Remaining: {final_stats['pending']} pending")
    
    print("\n" + "=" * 80)
    print("DEMO COMPLETE")
    print("=" * 80)
    
    queue.close()