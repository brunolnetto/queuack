# ETL Pipeline DAG

```mermaid
graph TD
    extractapi["extract_api"]
    extractdb["extract_db"]
    extractfiles["extract_files"]
    validateapi["validate_api"]
    validatedb["validate_db"]
    validatefiles["validate_files"]
    transformapi["transform_api"]
    transformdb["transform_db"]
    transformfiles["transform_files"]
    loadapi["load_api"]
    loaddb["load_db"]
    loadfiles["load_files"]
    aggregateresults["aggregate_results"]
    extractapi --> validateapi
    extractdb --> validatedb
    extractfiles --> validatefiles
    validateapi --> transformapi
    validatedb --> transformdb
    validatefiles --> transformfiles
    transformapi --> loadapi
    transformdb --> loaddb
    transformfiles --> loadfiles
    loadapi --> aggregateresults
    loaddb --> aggregateresults
    loadfiles --> aggregateresults

    classDef done fill:#90EE90
    classDef failed fill:#FFB6C6
    classDef skipped fill:#D3D3D3
    classDef running fill:#87CEEB
    classDef ready fill:#FFD700
```

## Pipeline Overview
- **Extract**: Parallel data extraction from multiple sources
- **Validate**: Data quality checks
- **Transform**: Data processing and enrichment
- **Load**: Data warehouse loading
- **Aggregate**: Final results aggregation
