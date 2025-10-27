#!/usr/bin/env python3
"""
Async API Fetching - I/O-Bound Workload Speedup

Demonstrates using @async_task decorator for concurrent API requests,
achieving 10-100x speedup compared to sequential requests.

# Difficulty: intermediate

Shows:
- @async_task decorator for async functions
- Concurrent HTTP requests with aiohttp
- Comparison: sync vs async performance
- Real-world API pagination handling
- Error handling in async context
"""

import asyncio
import sys
import time
from pathlib import Path
from typing import List, Dict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from queuack import DAG, DuckQueue, async_task


# ==============================================================================
# Simulated API (replace with real aiohttp in production)
# ==============================================================================

async def simulate_api_call(url: str, delay: float = 0.1) -> Dict:
    """Simulate network delay for API call."""
    await asyncio.sleep(delay)

    # Parse mock response based on URL
    if "users" in url:
        user_id = int(url.split("/")[-1])
        return {
            "id": user_id,
            "name": f"User {user_id}",
            "email": f"user{user_id}@example.com",
            "active": True
        }
    elif "orders" in url:
        user_id = int(url.split("user_id=")[1])
        return {
            "user_id": user_id,
            "orders": [
                {"id": f"ORD{user_id}01", "amount": 99.99},
                {"id": f"ORD{user_id}02", "amount": 149.50}
            ]
        }
    else:
        return {"data": f"Response from {url}"}


# ==============================================================================
# Traditional Sync Approach (SLOW)
# ==============================================================================

def fetch_users_sync(user_ids: List[int]) -> List[Dict]:
    """Fetch users sequentially - SLOW for many requests."""
    import time

    users = []
    for user_id in user_ids:
        # Simulate network delay
        time.sleep(0.1)
        users.append({
            "id": user_id,
            "name": f"User {user_id}",
            "email": f"user{user_id}@example.com"
        })

    return users


# ==============================================================================
# Async Approach (FAST)
# ==============================================================================

@async_task
async def fetch_users_async(user_ids: List[int]) -> List[Dict]:
    """Fetch users concurrently - 10x faster than sync."""

    async def fetch_one(user_id: int) -> Dict:
        url = f"https://api.example.com/users/{user_id}"
        return await simulate_api_call(url)

    # Execute all requests concurrently
    tasks = [fetch_one(user_id) for user_id in user_ids]
    results = await asyncio.gather(*tasks)

    return results


@async_task
async def fetch_orders_async(user_ids: List[int]) -> List[Dict]:
    """Fetch orders for all users concurrently."""

    async def fetch_orders_for_user(user_id: int) -> Dict:
        url = f"https://api.example.com/orders?user_id={user_id}"
        return await simulate_api_call(url)

    tasks = [fetch_orders_for_user(user_id) for user_id in user_ids]
    results = await asyncio.gather(*tasks)

    return results


@async_task
async def fetch_paginated_data(total_pages: int = 10) -> List[Dict]:
    """Fetch multiple pages concurrently."""

    async def fetch_page(page_num: int) -> Dict:
        url = f"https://api.example.com/data?page={page_num}"
        data = await simulate_api_call(url, delay=0.05)
        return {"page": page_num, "items": [data]}

    # Fetch all pages at once
    tasks = [fetch_page(i) for i in range(1, total_pages + 1)]
    pages = await asyncio.gather(*tasks)

    # Flatten results
    all_items = []
    for page_data in pages:
        all_items.extend(page_data["items"])

    return all_items


# ==============================================================================
# Real-world Example: User Data Enrichment Pipeline
# ==============================================================================

@async_task
async def enrich_user_data(user_ids: List[int]) -> List[Dict]:
    """Enrich user data with additional API calls."""

    async def enrich_one(user_id: int) -> Dict:
        # Fetch user and orders concurrently
        user_task = simulate_api_call(f"https://api.example.com/users/{user_id}")
        orders_task = simulate_api_call(f"https://api.example.com/orders?user_id={user_id}")

        user, orders = await asyncio.gather(user_task, orders_task)

        # Combine data
        return {
            **user,
            "total_orders": len(orders.get("orders", [])),
            "total_spent": sum(
                order["amount"] for order in orders.get("orders", [])
            )
        }

    tasks = [enrich_one(user_id) for user_id in user_ids]
    return await asyncio.gather(*tasks)


# ==============================================================================
# Performance Comparison
# ==============================================================================

def compare_sync_vs_async():
    """Compare sync vs async performance."""
    print("\n" + "="*70)
    print("⏱️  PERFORMANCE COMPARISON: Sync vs Async")
    print("="*70)

    user_ids = list(range(1, 51))  # 50 users

    # Sync approach
    print("\n1️⃣  Sync Approach (Sequential)")
    print(f"   Fetching {len(user_ids)} users sequentially...")

    start = time.perf_counter()
    sync_results = fetch_users_sync(user_ids)
    sync_duration = time.perf_counter() - start

    print(f"   ✓ Completed in {sync_duration:.2f}s")
    print(f"   ✓ Fetched {len(sync_results)} users")
    print(f"   ✓ Average: {sync_duration / len(user_ids) * 1000:.1f}ms per user")

    # Async approach
    print("\n2️⃣  Async Approach (Concurrent)")
    print(f"   Fetching {len(user_ids)} users concurrently...")

    start = time.perf_counter()
    async_results = fetch_users_async(user_ids)
    async_duration = time.perf_counter() - start

    print(f"   ✓ Completed in {async_duration:.2f}s")
    print(f"   ✓ Fetched {len(async_results)} users")
    print(f"   ✓ Average: {async_duration / len(user_ids) * 1000:.1f}ms per user")

    # Speedup
    speedup = sync_duration / async_duration
    print(f"\n🚀 Speedup: {speedup:.1f}x faster with async!")
    print(f"   Time saved: {sync_duration - async_duration:.2f}s ({(1 - async_duration/sync_duration) * 100:.1f}% reduction)")


# ==============================================================================
# DAG Workflow Functions (Module-level for pickling)
# ==============================================================================

USER_IDS = list(range(1, 26))  # 25 users

@async_task
async def dag_fetch_users():
    """Step 1: Fetch users."""
    print(f"\n   Step 1: Fetching {len(USER_IDS)} users...")

    async def fetch_one(user_id: int) -> Dict:
        url = f"https://api.example.com/users/{user_id}"
        return await simulate_api_call(url)

    tasks = [fetch_one(user_id) for user_id in USER_IDS]
    return await asyncio.gather(*tasks)


@async_task
async def dag_fetch_orders():
    """Step 2: Fetch orders."""
    print(f"   Step 2: Fetching orders for {len(USER_IDS)} users...")

    async def fetch_orders_for_user(user_id: int) -> Dict:
        url = f"https://api.example.com/orders?user_id={user_id}"
        return await simulate_api_call(url)

    tasks = [fetch_orders_for_user(user_id) for user_id in USER_IDS]
    return await asyncio.gather(*tasks)


@async_task
async def dag_fetch_pages():
    """Step 3: Fetch paginated data."""
    print("   Step 3: Fetching 20 pages of data...")

    async def fetch_page(page_num: int) -> Dict:
        url = f"https://api.example.com/data?page={page_num}"
        data = await simulate_api_call(url, delay=0.05)
        return {"page": page_num, "items": [data]}

    tasks = [fetch_page(i) for i in range(1, 21)]
    pages = await asyncio.gather(*tasks)

    # Flatten results
    all_items = []
    for page_data in pages:
        all_items.extend(page_data["items"])

    return all_items


def dag_combine_results(context):
    """Step 4: Combine all results."""
    from queuack import TaskContext
    users = context.upstream("fetch_users")
    orders = context.upstream("fetch_orders")
    pages = context.upstream("fetch_pages")

    print(f"   Step 4: Combining results...")
    print(f"            - Users: {len(users)}")
    print(f"            - Order responses: {len(orders)}")
    print(f"            - Page items: {len(pages)}")

    return {
        "users_count": len(users),
        "orders_count": len(orders),
        "pages_count": len(pages),
        "status": "success"
    }


# ==============================================================================
# DAG Workflow Example
# ==============================================================================

def run_dag_workflow():
    """Run async tasks in DAG workflow."""
    print("\n" + "="*70)
    print("📊 DAG WORKFLOW: Async API Pipeline")
    print("="*70)

    queue = DuckQueue(db_path=":memory:")
    dag = DAG("async_api_pipeline", queue=queue)

    # Build DAG
    dag.add_node(dag_fetch_users, name="fetch_users")
    dag.add_node(dag_fetch_orders, name="fetch_orders")
    dag.add_node(dag_fetch_pages, name="fetch_pages")
    dag.add_node(
        dag_combine_results,
        name="combine",
        depends_on=["fetch_users", "fetch_orders", "fetch_pages"]
    )

    # Execute
    print("\n🚀 Executing DAG with async tasks...")
    start = time.perf_counter()
    dag.execute()
    duration = time.perf_counter() - start

    print(f"\n✅ Pipeline completed in {duration:.2f}s")
    print(f"   All async tasks executed successfully")

    queue.close()


# ==============================================================================
# Real-world Use Cases
# ==============================================================================

def real_world_examples():
    """Show real-world async use cases."""
    print("\n" + "="*70)
    print("🌍 REAL-WORLD USE CASES")
    print("="*70)

    print("""
1️⃣  **API Aggregation**
   - Fetch data from multiple APIs concurrently
   - Example: Combining weather, traffic, news APIs
   - Speedup: 10-50x faster than sequential

2️⃣  **Web Scraping**
   - Scrape thousands of pages concurrently
   - Example: Product prices from e-commerce sites
   - Speedup: 20-100x faster

3️⃣  **Database Queries**
   - Run multiple independent queries concurrently
   - Example: Fetching user, orders, analytics separately
   - Speedup: 5-20x faster

4️⃣  **File I/O Operations**
   - Read/write multiple files concurrently
   - Example: Processing log files, CSV exports
   - Speedup: 10-30x faster on SSDs

5️⃣  **Microservice Calls**
   - Call multiple microservices concurrently
   - Example: User service, payment service, inventory service
   - Speedup: 5-15x faster
    """)


# ==============================================================================
# Best Practices
# ==============================================================================

def best_practices():
    """Show async best practices."""
    print("\n" + "="*70)
    print("💡 ASYNC BEST PRACTICES")
    print("="*70)

    print("""
✅ **When to Use Async:**
   - I/O-bound tasks (network, disk, database)
   - Multiple independent operations
   - High-latency operations (APIs, remote calls)

❌ **When NOT to Use Async:**
   - CPU-bound tasks (use multiprocessing instead)
   - Single sequential operation
   - Tasks with shared mutable state

📋 **Implementation Tips:**
   1. Use @async_task decorator for simple async functions
   2. Use asyncio.gather() for concurrent execution
   3. Handle errors with try/except in async functions
   4. Set reasonable timeouts for network calls
   5. Use connection pooling for databases
   6. Limit concurrency with Semaphore if needed

🚨 **Common Pitfalls:**
   - Don't use time.sleep() in async functions (use await asyncio.sleep())
   - Don't forget to await async function calls
   - Don't share non-thread-safe objects between tasks
   - Don't ignore timeouts (always set limits)
    """)


# ==============================================================================
# Main
# ==============================================================================

def main():
    """Run all async examples."""
    print("🦆"*35)
    print("  Async API Fetching - I/O Speedup Demo")
    print("  @async_task Decorator")
    print("🦆"*35)

    compare_sync_vs_async()
    run_dag_workflow()
    real_world_examples()
    best_practices()

    print("\n" + "="*70)
    print("📚 SUMMARY")
    print("="*70)
    print("""
The @async_task decorator enables:
- ✅ 10-100x speedup for I/O-bound workloads
- ✅ Seamless integration with DAG workflows
- ✅ Automatic event loop management
- ✅ Works with both sync and async tasks in same DAG

Perfect for:
- API requests
- Web scraping
- Database queries
- File I/O
- Microservice calls

Get started:
    from queuack import async_task

    @async_task
    async def fetch_data():
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                return await response.json()

    # Call synchronously - decorator handles event loop
    result = fetch_data()
    """)
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
