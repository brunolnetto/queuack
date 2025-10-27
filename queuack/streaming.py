"""
Streaming module for efficient memory-efficient processing of large datasets.

This module provides StreamWriter and StreamReader classes that enable
O(1) memory usage when working with datasets containing millions of rows.

Supported formats:
- JSONL: JSON Lines (one JSON object per line)
- Pickle: Python pickle format (supports any Python object)
- CSV: Comma-separated values (requires dict records with consistent keys)
- Parquet: Apache Parquet columnar format (requires pyarrow)
"""

import csv
import json
import pickle
import struct
from pathlib import Path
from typing import Any, Iterator, Literal, Optional, Union


class StreamWriter:
    """Writes generator output to file with O(1) memory usage.

    Supports multiple formats for streaming large datasets to disk
    without loading everything into memory.

    Attributes:
        path: File path to write to
        format: Output format - 'jsonl', 'pickle', 'csv', or 'parquet'

    Example:
        Basic usage with JSONL:

        >>> def generate_data():
        ...     for i in range(1000000):
        ...         yield {"id": i, "value": i * 2}
        >>>
        >>> writer = StreamWriter("data.jsonl", format="jsonl")
        >>> count = writer.write(generate_data())
        >>> print(f"Wrote {count} items")
        Wrote 1000000 items

        Using CSV format:

        >>> writer = StreamWriter("data.csv", format="csv")
        >>> count = writer.write(generate_data())

        Using Parquet format (requires pyarrow):

        >>> writer = StreamWriter("data.parquet", format="parquet")
        >>> count = writer.write(generate_data())

    Note:
        - JSONL format: One JSON object per line, human-readable
        - Pickle format: Binary format, supports complex Python objects
        - CSV format: Comma-separated values, requires dict records
        - Parquet format: Columnar format, requires pyarrow library
        - Format auto-detected from file extension if not specified
    """

    def __init__(
        self,
        path: Union[str, Path],
        format: Optional[Literal["jsonl", "pickle", "csv", "parquet"]] = None
    ):
        """Initialize StreamWriter.

        Args:
            path: File path to write to
            format: Output format ('jsonl', 'pickle', 'csv', 'parquet').
                If None, auto-detects from file extension

        Raises:
            ValueError: If format cannot be determined or is invalid
        """
        self.path = Path(path)

        if format is None:
            # Auto-detect format from extension
            suffix = self.path.suffix.lower()
            if suffix in ['.jsonl', '.json']:
                format = 'jsonl'
            elif suffix in ['.pkl', '.pickle']:
                format = 'pickle'
            elif suffix == '.csv':
                format = 'csv'
            elif suffix in ['.parquet', '.pq']:
                format = 'parquet'
            else:
                raise ValueError(
                    f"Cannot auto-detect format from extension '{suffix}'. "
                    "Please specify format explicitly."
                )

        if format not in ['jsonl', 'pickle', 'csv', 'parquet']:
            raise ValueError(
                f"Invalid format '{format}'. "
                f"Must be 'jsonl', 'pickle', 'csv', or 'parquet'"
            )

        self.format = format

    def write(self, generator: Iterator[Any]) -> int:
        """Write generator output to file.

        Iterates through the generator and writes each item to disk
        without accumulating items in memory.

        Args:
            generator: Iterator/generator yielding items to write

        Returns:
            Number of items written

        Raises:
            IOError: If file cannot be written
            TypeError: If items cannot be serialized in chosen format
            ImportError: If format requires unavailable library (e.g., pyarrow)

        Example:
            >>> def data_gen():
            ...     for i in range(100):
            ...         yield {"id": i}
            >>>
            >>> writer = StreamWriter("output.jsonl")
            >>> count = writer.write(data_gen())
            >>> print(count)
            100
        """
        # Ensure parent directory exists
        self.path.parent.mkdir(parents=True, exist_ok=True)

        count = 0

        if self.format == 'jsonl':
            with open(self.path, 'w', encoding='utf-8') as f:
                for item in generator:
                    # Write each item as a single line of JSON
                    json_str = json.dumps(item, ensure_ascii=False)
                    f.write(json_str + '\n')
                    count += 1

        elif self.format == 'pickle':
            with open(self.path, 'wb') as f:
                for item in generator:
                    # Pickle each item with length prefix for reading
                    pickled = pickle.dumps(item)
                    # Write length as 4-byte unsigned int, then data
                    f.write(struct.pack('I', len(pickled)))
                    f.write(pickled)
                    count += 1

        elif self.format == 'csv':
            with open(self.path, 'w', encoding='utf-8', newline='') as f:
                writer = None
                for item in generator:
                    if not isinstance(item, dict):
                        raise TypeError(
                            f"CSV format requires dict items, got {type(item).__name__}"
                        )

                    # Initialize CSV writer with headers from first item
                    if writer is None:
                        fieldnames = list(item.keys())
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()

                    writer.writerow(item)
                    count += 1

        elif self.format == 'parquet':
            try:
                import pyarrow as pa
                import pyarrow.parquet as pq
            except ImportError:
                raise ImportError(
                    "Parquet format requires pyarrow. "
                    "Install with: pip install pyarrow"
                )

            # For Parquet, we need to batch items for efficient writing
            # Use a reasonable batch size
            batch_size = 10000
            batch = []

            for item in generator:
                batch.append(item)
                count += 1

                # Write batch when it reaches batch_size
                if len(batch) >= batch_size:
                    if count == len(batch):
                        # First batch - create the file
                        table = pa.Table.from_pylist(batch)
                        writer = pq.ParquetWriter(self.path, table.schema)
                        writer.write_table(table)
                    else:
                        # Subsequent batches
                        table = pa.Table.from_pylist(batch)
                        writer.write_table(table)
                    batch = []

            # Write remaining items
            if batch:
                if count == len(batch):
                    # Only one batch (small dataset)
                    table = pa.Table.from_pylist(batch)
                    pq.write_table(table, self.path)
                else:
                    # Final partial batch
                    table = pa.Table.from_pylist(batch)
                    writer.write_table(table)
                    writer.close()
            elif count > 0:
                # Close writer if we have data
                writer.close()

        return count


class StreamReader:
    """Lazy iteration over file written by StreamWriter.

    Reads items one at a time from disk without loading the entire
    file into memory, enabling O(1) memory processing of large datasets.

    Attributes:
        path: File path to read from
        format: Input format - 'jsonl', 'pickle', 'csv', or 'parquet'

    Example:
        Reading JSONL file:

        >>> reader = StreamReader("data.jsonl")
        >>> for item in reader:
        ...     process(item)  # Each item loaded one at a time

        Reading CSV file:

        >>> reader = StreamReader("data.csv", format="csv")
        >>> for row in reader:
        ...     print(row)  # Dict with column names as keys

        Reading Parquet file:

        >>> reader = StreamReader("data.parquet")
        >>> for item in reader:
        ...     process(item)  # Reads in batches internally

        Memory-efficient aggregation:

        >>> reader = StreamReader("large_file.jsonl")
        >>> total = sum(item['value'] for item in reader)
        >>> # Only one item in memory at a time!

    Note:
        - StreamReader is lazy - no data loaded until iteration starts
        - Can iterate multiple times by creating new iterator
        - Safe to use with files of any size (100GB+)
        - Parquet reads in batches for efficiency but yields one row at a time
    """

    def __init__(
        self,
        path: Union[str, Path],
        format: Optional[Literal["jsonl", "pickle", "csv", "parquet"]] = None
    ):
        """Initialize StreamReader.

        Args:
            path: File path to read from
            format: Input format ('jsonl', 'pickle', 'csv', 'parquet').
                If None, auto-detects from file extension

        Raises:
            ValueError: If format cannot be determined or is invalid
            FileNotFoundError: If file does not exist
        """
        self.path = Path(path)

        if not self.path.exists():
            raise FileNotFoundError(f"File not found: {self.path}")

        if format is None:
            # Auto-detect format from extension
            suffix = self.path.suffix.lower()
            if suffix in ['.jsonl', '.json']:
                format = 'jsonl'
            elif suffix in ['.pkl', '.pickle']:
                format = 'pickle'
            elif suffix == '.csv':
                format = 'csv'
            elif suffix in ['.parquet', '.pq']:
                format = 'parquet'
            else:
                raise ValueError(
                    f"Cannot auto-detect format from extension '{suffix}'. "
                    "Please specify format explicitly."
                )

        if format not in ['jsonl', 'pickle', 'csv', 'parquet']:
            raise ValueError(
                f"Invalid format '{format}'. "
                f"Must be 'jsonl', 'pickle', 'csv', or 'parquet'"
            )

        self.format = format

    def __iter__(self) -> Iterator[Any]:
        """Iterate over items in file lazily.

        Yields:
            Items from file, one at a time

        Raises:
            IOError: If file cannot be read
            ValueError: If file is corrupted or invalid
            ImportError: If format requires unavailable library

        Example:
            >>> reader = StreamReader("data.jsonl")
            >>> for item in reader:
            ...     print(item['id'])
        """
        if self.format == 'jsonl':
            with open(self.path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.rstrip('\n\r')
                    if not line:
                        # Skip empty lines
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError as e:
                        raise ValueError(
                            f"Invalid JSON on line {line_num}: {e}"
                        ) from e

        elif self.format == 'pickle':
            with open(self.path, 'rb') as f:
                while True:
                    # Read length prefix
                    length_bytes = f.read(4)
                    if not length_bytes:
                        # End of file
                        break

                    if len(length_bytes) < 4:
                        raise ValueError(
                            "Corrupted pickle file: incomplete length prefix"
                        )

                    # Unpack length
                    length = struct.unpack('I', length_bytes)[0]

                    # Read pickled data
                    pickled = f.read(length)
                    if len(pickled) < length:
                        raise ValueError(
                            "Corrupted pickle file: incomplete data"
                        )

                    # Unpickle and yield
                    yield pickle.loads(pickled)

        elif self.format == 'csv':
            with open(self.path, 'r', encoding='utf-8', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    yield row

        elif self.format == 'parquet':
            try:
                import pyarrow.parquet as pq
            except ImportError:
                raise ImportError(
                    "Parquet format requires pyarrow. "
                    "Install with: pip install pyarrow"
                )

            # Read parquet file in batches for memory efficiency
            parquet_file = pq.ParquetFile(self.path)

            for batch in parquet_file.iter_batches(batch_size=10000):
                # Convert batch to list of dicts and yield one at a time
                for row in batch.to_pylist():
                    yield row
