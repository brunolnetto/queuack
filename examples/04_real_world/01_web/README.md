# Web & API Examples

Real-world patterns for web scraping, image processing, and API interactions.

## Examples

### 02_web_scraper.py
**Distributed web scraping with rate limiting**
- Concurrent HTTP requests
- Rate limiting per domain
- Retry with backoff
- robots.txt compliance
- Result aggregation

**Difficulty:** intermediate

### 03_image_processing.py
**Parallel image processing**
- Batch image transformations
- Thumbnail generation
- Format conversion
- Concurrent processing
- Progress tracking

**Difficulty:** intermediate

### 04_report_generation.py
**Report generation with parallel data fetching**
- Fetch from multiple sources
- Aggregate results
- Generate formatted output
- PDF/HTML export
- Error handling

**Difficulty:** intermediate

### 09_async_api_fetching.py
**Async I/O for 50x speedup (API requests)**
- Async/await patterns
- Concurrent API calls
- 10-100x faster than sync
- Rate limiting
- Error recovery

**Difficulty:** intermediate

## Quick Start

```python
from queuack import DuckQueue, async_task

@async_task
async def fetch_api(url: str):
    """Async API fetching."""
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.json()

queue = DuckQueue("api.db")
job_ids = [queue.enqueue(fetch_api, args=(url,)) for url in urls]
```

## Key Features

- **Async I/O**: 50-100x speedup for I/O-bound tasks
- **Rate limiting**: Respect API limits
- **Concurrent**: Process multiple requests in parallel
- **Resilient**: Built-in retry and error handling

See [main README](../../../README.md) for more details.
