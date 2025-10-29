"""Advanced retry patterns and failure recovery strategies.

# Difficulty: advanced
"""

import random
import time

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue, Worker


class RetryStrategiesDemo:
    """Demonstrate various retry strategies."""

    def __init__(self):
        self.db_path = create_temp_path("retry_demo")
        self.queue = DuckQueue(self.db_path)
        self.worker = Worker(self.queue, worker_id="retry-demo", concurrency=1)

    @staticmethod
    def flaky_api_call(attempt_num: int = 0, strategy: str = "exponential"):
        """Simulate API that fails initially but succeeds after retries."""
        failure_rate = {
            "exponential": 0.7,  # 70% failure rate
            "linear": 0.6,  # 60% failure rate
            "circuit_breaker": 0.8,  # 80% failure rate
            "jittered": 0.7,  # 70% failure rate
        }.get(strategy, 0.7)

        if random.random() < failure_rate and attempt_num < 3:
            raise Exception(f"API error (attempt {attempt_num}, strategy: {strategy})")

        return f"✅ Success after {attempt_num} attempts using {strategy} strategy!"

    def exponential_backoff_enqueue(self):
        """Demonstrate exponential backoff with jitter."""
        print("\n📈 Exponential Backoff Strategy")

        for i in range(3):
            # Exponential backoff: 1s, 2s, 4s, 8s, 16s
            base_delay = 2**i
            # Add jitter (±25%) to prevent thundering herd
            jitter = random.uniform(-0.25, 0.25) * base_delay
            delay = max(0.1, base_delay + jitter)

            self.queue.enqueue(
                RetryStrategiesDemo.flaky_api_call,
                args=(i, "exponential"),
                delay_seconds=delay,
                max_attempts=1,  # Manual retry handling
            )
            print(".1f")

    def linear_backoff_enqueue(self):
        """Demonstrate linear backoff."""
        print("\n📊 Linear Backoff Strategy")

        for i in range(3):
            # Linear backoff: 1s, 2s, 3s, 4s, 5s
            delay = i + 1

            self.queue.enqueue(
                RetryStrategiesDemo.flaky_api_call,
                args=(i, "linear"),
                delay_seconds=delay,
                max_attempts=1,
            )
            print(".1f")

    def circuit_breaker_enqueue(self):
        """Demonstrate circuit breaker pattern."""
        print("\n🔌 Circuit Breaker Strategy")

        # Simulate circuit breaker: fast fail after consecutive failures
        consecutive_failures = 0

        for i in range(5):
            if consecutive_failures >= 2:
                print(
                    f"  🚫 Circuit breaker tripped after {consecutive_failures} failures - fast failing"
                )
                # In real circuit breaker, we'd enqueue to different queue or skip
                continue

            try:
                result = RetryStrategiesDemo.flaky_api_call(i, "circuit_breaker")
                consecutive_failures = 0
                print(f"  {result}")
            except Exception as e:
                consecutive_failures += 1
                print(f"  ❌ {e} (failures: {consecutive_failures})")

                # Circuit breaker: longer delays after failures
                delay = min(30, 2**consecutive_failures)  # Cap at 30s

                self.queue.enqueue(
                    RetryStrategiesDemo.flaky_api_call,
                    args=(i, "circuit_breaker"),
                    delay_seconds=delay,
                    max_attempts=1,
                )
                print(".1f")

    def jittered_exponential_enqueue(self):
        """Demonstrate jittered exponential backoff."""
        print("\n🎲 Jittered Exponential Backoff Strategy")

        for i in range(3):
            # Base exponential delay
            base_delay = 2**i
            # Add significant jitter to distribute load
            jitter_range = base_delay * 0.5  # ±50% jitter
            delay = base_delay + random.uniform(-jitter_range, jitter_range)
            delay = max(0.1, delay)

            self.queue.enqueue(
                RetryStrategiesDemo.flaky_api_call,
                args=(i, "jittered"),
                delay_seconds=delay,
                max_attempts=1,
            )
            print(".1f")

    def run_demo(self):
        """Run the complete retry strategies demonstration."""
        print("🚀 Advanced Retry Strategies Demo")
        print("=" * 50)

        # Enqueue jobs with different strategies
        self.exponential_backoff_enqueue()
        self.linear_backoff_enqueue()
        self.circuit_breaker_enqueue()
        self.jittered_exponential_enqueue()

        print("\n🏃 Starting worker to process retry jobs...")
        print("(Jobs will be processed with their respective delays)")

        # Create worker to process the jobs
        from queuack import Worker

        worker = Worker(self.queue, worker_id="retry-demo-worker", concurrency=1)

        # Start worker in a thread so we can stop it after processing
        import threading

        worker_thread = threading.Thread(target=worker.run, args=(0.1,))
        worker_thread.start()

        # Let jobs process for a reasonable time
        time.sleep(15)  # Allow time for retries with delays

        # Stop the worker
        worker.should_stop = True
        worker_thread.join(timeout=2)

        print("⏱️  Demo completed - jobs were processed with various retry strategies")

        print("\n✅ Retry strategies demo completed!")
        print("\nKey takeaways:")
        print("• Exponential backoff prevents overwhelming failing services")
        print("• Jitter distributes retry load to prevent thundering herd")
        print(
            "• Circuit breakers provide fast failure for consistently failing services"
        )
        print("• Linear backoff offers predictable retry timing")


def main():
    demo = RetryStrategiesDemo()
    demo.run_demo()


if __name__ == "__main__":
    main()
