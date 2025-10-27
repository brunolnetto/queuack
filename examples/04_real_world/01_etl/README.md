# ETL & Data Pipeline Examples

Production-ready ETL patterns for data engineering workflows.

## Examples

### 01_etl_pipeline.py
**Complete ETL with error handling**
- Extract from multiple sources
- Transform with validation
- Load to destination
- Retry on failures
- Progress tracking

**Difficulty:** intermediate

### 06_spark_etl.py
**Integration with Apache Spark**
- Spark DataFrame transformations
- Distributed processing
- Queuack orchestration
- Batch data processing

**Difficulty:** intermediate

### 07_streaming_etl.py
**Memory-efficient streaming ETL (1M+ records)**
- Constant memory usage (~50MB)
- Process millions of records
- Generator-based streaming
- Parquet output format
- O(1) memory complexity

**Difficulty:** intermediate

### 08_streaming_formats.py
**Multi-format exports (JSONL/CSV/Parquet/Pickle)**
- Stream to multiple formats
- Memory-efficient serialization
- Format comparison benchmarks
- Production-ready patterns

**Difficulty:** intermediate

## Quick Start

```python
from queuack import DuckQueue, generator_task

@generator_task(format="parquet")
def extract_data():
    """Stream data from source."""
    for record in fetch_from_source():
        yield record

queue = DuckQueue("etl.db")
job_id = queue.enqueue(extract_data)
```

## Key Features

- **Streaming**: Process datasets larger than RAM
- **Memory efficient**: Constant ~50MB memory usage
- **Multiple formats**: JSONL, CSV, Parquet, Pickle
- **Spark integration**: Orchestrate distributed processing
- **Error handling**: Built-in retry and recovery

See [main README](../../../README.md) for more details.
