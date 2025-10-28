"""
Report Generation: Parallel Data Aggregation and Visualization

This example demonstrates report generation pipelines that fetch data from
multiple sources in parallel, merge the results, and generate formatted reports.
This pattern is common in business intelligence and analytics workflows.

Report Workflow:
   Fetch Sales ┐
               ├──→ Merge → Generate PDF
   Fetch Inventory ┘

Key Components:
- Data Fetching: Parallel retrieval from multiple data sources
- Data Merging: Combine datasets with proper joins and validation
- Report Generation: Create formatted output (PDF, Excel, etc.)
- Multi-region Processing: Handle data from different geographical areas

Real-world Use Cases:
- Business dashboards (sales + inventory reports)
- Financial statements (revenue + expense aggregation)
- Performance analytics (multiple KPI sources)
- Compliance reporting (data from various systems)
- Executive summaries (aggregated business metrics)

Queuack Features Demonstrated:
- Fan-in pattern (multiple sources → single merge point)
- Parallel data fetching for performance
- Dependency synchronization for data consistency
- Multiple independent pipelines (one per region)
- Result aggregation and formatting

Advanced Topics:
- Data consistency: Ensuring merged data is accurate
- Performance optimization: Parallel fetching reduces latency
- Scalability: Processing multiple regions independently
- Format flexibility: Supporting different output formats
- Error handling: Managing failures in data sources

# Difficulty: advanced
"""

from examples.utils.tempfile import create_temp_path
from queuack import DuckQueue

db_path = create_temp_path("reports")
queue = DuckQueue(db_path)


def fetch_sales_data(region: str):
    """Fetch sales data for region."""
    print(f"Fetching sales for {region}...")
    return {"region": region, "sales": 100000}


def fetch_inventory_data(region: str):
    """Fetch inventory data."""
    print(f"Fetching inventory for {region}...")
    return {"region": region, "inventory": 5000}


def merge_data(sales, inventory):
    """Merge datasets."""
    return {**sales, **inventory}


def generate_pdf(data: dict):
    """Generate PDF report."""
    print(f"Generating report for {data['region']}...")
    return f"report_{data['region']}.pdf"


regions = ["north", "south", "east", "west"]

for region in regions:
    with queue.dag(f"report_{region}") as dag:
        sales = dag.enqueue(fetch_sales_data, args=(region,), name="fetch_sales")
        inventory = dag.enqueue(
            fetch_inventory_data, args=(region,), name="fetch_inventory"
        )
        merge = dag.enqueue(
            merge_data, name="merge", depends_on=["fetch_sales", "fetch_inventory"]
        )
        pdf = dag.enqueue(generate_pdf, name="generate_pdf", depends_on="merge")
