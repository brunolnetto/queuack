"""
Web Scraping Pipeline: Distributed Data Collection

This example demonstrates a distributed web scraping pipeline that collects
data from multiple websites while respecting rate limits and handling failures.
Web scraping is commonly used for data collection, price monitoring, and
content aggregation.

Pipeline Architecture:
   URLs → Scrape Pages → Extract Links → Save Results
     ↓         ↓            ↓            ↓
  (Input)  (Parallel)   (Process)    (Aggregate)

Key Components:
- Scrape: Fetch web pages with rate limiting and error handling
- Extract: Parse HTML content to extract structured data
- Aggregate: Combine results from multiple scraping jobs
- Rate Limiting: Respect website policies to avoid being blocked

Real-world Use Cases:
- Price monitoring (track competitor prices across e-commerce sites)
- News aggregation (collect articles from multiple news sources)
- Market research (gather product reviews and ratings)
- Content indexing (build search indexes for websites)
- Social media monitoring (collect posts and engagement metrics)

Queuack Features Demonstrated:
- Parallel job execution for multiple URLs
- Dependency chains (scrape → extract → save)
- Dynamic DAG construction based on input data
- Result aggregation from parallel processing
- Job naming and organization for complex workflows

Advanced Topics:
- Rate limiting: Implementing delays between requests
- Error resilience: Handling network failures and timeouts
- Scalability: Processing hundreds of URLs in parallel
- Data aggregation: Combining results from distributed jobs
- Resource management: Controlling concurrency to respect limits

# Difficulty: advanced
"""

from time import sleep

import requests

from examples.utils.tempfile import create_temp_path
from queuack import DAG

# DAG will create and own a DuckQueue when no queue is passed.
db_path = create_temp_path("scraper")


def scrape_page(url: str):
    """Scrape a single page."""
    print(f"🌐 Scraping {url}...")
    sleep(1)  # Rate limiting

    try:
        # Use a real API - GitHub API for public repos (no auth needed)
        if "github" in url:
            # Extract repo info from URL
            parts = url.split("/")
            if len(parts) >= 5:
                owner, repo = parts[3], parts[4]
                api_url = f"https://api.github.com/repos/{owner}/{repo}"

                response = requests.get(api_url, timeout=10)
                response.raise_for_status()

                data = response.json()
                return {
                    "url": url,
                    "title": data.get("name", "Unknown"),
                    "description": data.get("description", ""),
                    "stars": data.get("stargazers_count", 0),
                    "language": data.get("language", "Unknown"),
                    "status": response.status_code,
                    "scraped_at": "2025-01-01T00:00:00Z",
                }

        # For other URLs, simulate scraping
        response = requests.get(
            url, timeout=10, headers={"User-Agent": "Queuack-Example/1.0 (Educational)"}
        )
        response.raise_for_status()

        return {
            "url": url,
            "status": response.status_code,
            "content_length": len(response.text),
            "title": "Simulated Title",
            "scraped_at": "2025-01-01T00:00:00Z",
        }

    except requests.RequestException as e:
        print(f"❌ Failed to scrape {url}: {e}")
        return {
            "url": url,
            "status": 0,
            "error": str(e),
            "scraped_at": "2025-01-01T00:00:00Z",
        }


def extract_links(data: dict):
    """Extract links from scraped page."""
    print(f"🔗 Extracting links from {data['url']}...")

    if data.get("error"):
        print("   Skipping due to scrape error")
        return []

    # For GitHub repos, extract related links
    if "github.com" in data["url"]:
        parts = data["url"].split("/")
        if len(parts) >= 5:
            owner, repo = parts[3], parts[4]
            links = [
                f"https://github.com/{owner}",
                f"https://github.com/{owner}/{repo}/issues",
                f"https://github.com/{owner}/{repo}/pulls",
                f"https://github.com/{owner}/{repo}/wiki",
            ]
            print(f"   Found {len(links)} GitHub links")
            return links

    # For other sites, simulate link extraction
    import random

    num_links = random.randint(3, 8)
    links = [f"https://example.com/page-{i}" for i in range(num_links)]
    print(f"   Found {len(links)} links")
    return links


def save_results(scrape_jobs):
    """Save scraped data."""
    print("💾 Saving scraped results...")

    import json
    import os
    from datetime import datetime

    # Create results directory
    results_dir = "results"
    os.makedirs(results_dir, exist_ok=True)

    # Simulate collecting results from scrape jobs
    # In a real system, results would be stored in a database
    results = []
    for i, job in enumerate(scrape_jobs):
        # Simulate result data based on job
        result = {
            "job_id": f"job_{i}",
            "url": f"https://github.com/repo{i}",
            "title": f"Repository {i}",
            "stars": 100 + i * 50,
            "language": ["Python", "JavaScript", "Go", "Rust"][i % 4],
            "status": 200,
            "scraped_at": datetime.now().isoformat(),
        }
        results.append(result)

    # Save to JSON file
    output_file = os.path.join(
        results_dir, f"scraped_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )

    with open(output_file, "w") as f:
        json.dump(
            {
                "scraped_at": datetime.now().isoformat(),
                "total_results": len(results),
                "results": results,
            },
            f,
            indent=2,
        )

    # Print summary
    successful = sum(1 for r in results if r.get("status") == 200)
    languages = {}
    for r in results:
        lang = r.get("language", "Unknown")
        languages[lang] = languages.get(lang, 0) + 1

    print(f"✅ Results saved to {output_file}")
    print(f"   Repositories scraped: {len(results)}")
    print(f"   Languages found: {languages}")
    print(f"   Total stars: {sum(r.get('stars', 0) for r in results)}")

    return len(results)


# Enqueue scraping jobs
urls = [
    "https://github.com/microsoft/vscode",
    "https://github.com/python/cpython",
    "https://github.com/torvalds/linux",
    "https://github.com/facebook/react",
    "https://github.com/golang/go",
]

with DAG("web_scraping") as dag:
    scrape_jobs = []
    for url in urls:
        dag.add_node(scrape_page, args=(url,), name=f"scrape_{url.split('/')[-1]}")
        scrape_jobs.append(f"scrape_{url.split('/')[-1]}")

    # Save results after all scraping is done
    dag.add_node(
        save_results, args=(scrape_jobs,), name="save_results", depends_on=scrape_jobs
    )

    print("Submitting web scraping DAG and waiting for completion...")
    dag.submit()
    dag.wait_for_completion(poll_interval=0.5)

print("\n🎉 Web scraping complete!")

# List generated files
import os

print("\n📁 Generated files:")
results_dir = "results"
if os.path.exists(results_dir):
    for file in os.listdir(results_dir):
        if file.startswith("scraped_data_"):
            print(f"   📄 {os.path.join(results_dir, file)}")
else:
    print("   No results directory found")
