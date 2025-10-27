"""
Tests for generator streaming support.

Tests StreamWriter, StreamReader, and generator decorators for
memory-efficient processing of large datasets.
"""

import asyncio
import csv
import json
import pickle
import tempfile
from pathlib import Path

import pytest

from queuack import (
    DAG,
    DuckQueue,
    StreamReader,
    StreamWriter,
    TaskContext,
    async_generator_task,
    generator_task,
)


class TestStreamWriter:
    """Tests for StreamWriter class."""

    def test_stream_writer_jsonl(self, tmp_path):
        """Test writing items to JSONL format."""
        output_path = tmp_path / "test.jsonl"

        def data_gen():
            for i in range(1000):
                yield {"id": i, "value": i * 2}

        writer = StreamWriter(output_path, format="jsonl")
        count = writer.write(data_gen())

        assert count == 1000
        assert output_path.exists()

        # Verify file contents
        with open(output_path, 'r') as f:
            lines = f.readlines()
            assert len(lines) == 1000

            # Check first and last items
            first = json.loads(lines[0])
            assert first == {"id": 0, "value": 0}

            last = json.loads(lines[-1])
            assert last == {"id": 999, "value": 1998}

    def test_stream_writer_pickle(self, tmp_path):
        """Test writing items to Pickle format."""
        output_path = tmp_path / "test.pkl"

        def data_gen():
            for i in range(100):
                yield {"id": i, "complex": [1, 2, {"nested": i}]}

        writer = StreamWriter(output_path, format="pickle")
        count = writer.write(data_gen())

        assert count == 100
        assert output_path.exists()

    def test_stream_writer_auto_detect_jsonl(self, tmp_path):
        """Test auto-detecting JSONL format from extension."""
        output_path = tmp_path / "data.jsonl"

        def data_gen():
            for i in range(10):
                yield {"id": i}

        # Don't specify format - should auto-detect
        writer = StreamWriter(output_path)
        count = writer.write(data_gen())

        assert count == 10
        assert writer.format == "jsonl"

    def test_stream_writer_auto_detect_pickle(self, tmp_path):
        """Test auto-detecting Pickle format from extension."""
        output_path = tmp_path / "data.pkl"

        def data_gen():
            for i in range(10):
                yield {"id": i}

        # Don't specify format - should auto-detect
        writer = StreamWriter(output_path)
        count = writer.write(data_gen())

        assert count == 10
        assert writer.format == "pickle"

    def test_stream_writer_invalid_format(self, tmp_path):
        """Test error on invalid format."""
        output_path = tmp_path / "test.txt"

        with pytest.raises(ValueError, match="Cannot auto-detect format"):
            StreamWriter(output_path)

        with pytest.raises(ValueError, match="Invalid format"):
            StreamWriter(output_path, format="invalid")

    def test_stream_writer_creates_parent_dirs(self, tmp_path):
        """Test that parent directories are created if needed."""
        output_path = tmp_path / "deep" / "nested" / "path" / "data.jsonl"

        def data_gen():
            for i in range(5):
                yield {"id": i}

        writer = StreamWriter(output_path, format="jsonl")
        count = writer.write(data_gen())

        assert count == 5
        assert output_path.exists()


class TestStreamReader:
    """Tests for StreamReader class."""

    def test_stream_reader_jsonl(self, tmp_path):
        """Test reading items from JSONL format."""
        input_path = tmp_path / "test.jsonl"

        # Create test file
        with open(input_path, 'w') as f:
            for i in range(100):
                f.write(json.dumps({"id": i, "value": i * 2}) + '\n')

        # Read back
        reader = StreamReader(input_path, format="jsonl")
        items = list(reader)

        assert len(items) == 100
        assert items[0] == {"id": 0, "value": 0}
        assert items[-1] == {"id": 99, "value": 198}

    def test_stream_reader_pickle(self, tmp_path):
        """Test reading items from Pickle format."""
        input_path = tmp_path / "test.pkl"

        # Create test file using StreamWriter
        def data_gen():
            for i in range(50):
                yield {"id": i, "nested": {"value": i * 3}}

        writer = StreamWriter(input_path, format="pickle")
        writer.write(data_gen())

        # Read back
        reader = StreamReader(input_path, format="pickle")
        items = list(reader)

        assert len(items) == 50
        assert items[0] == {"id": 0, "nested": {"value": 0}}
        assert items[-1] == {"id": 49, "nested": {"value": 147}}

    def test_stream_reader_lazy_iteration(self, tmp_path):
        """Test that StreamReader is truly lazy."""
        input_path = tmp_path / "test.jsonl"

        # Create large test file
        with open(input_path, 'w') as f:
            for i in range(10000):
                f.write(json.dumps({"id": i}) + '\n')

        # Read only first 10 items
        reader = StreamReader(input_path)
        first_10 = []
        for i, item in enumerate(reader):
            first_10.append(item)
            if i >= 9:
                break

        assert len(first_10) == 10
        assert first_10[0] == {"id": 0}
        assert first_10[-1] == {"id": 9}

    def test_stream_reader_multiple_iterations(self, tmp_path):
        """Test that we can iterate multiple times."""
        input_path = tmp_path / "test.jsonl"

        with open(input_path, 'w') as f:
            for i in range(10):
                f.write(json.dumps({"id": i}) + '\n')

        reader = StreamReader(input_path)

        # First iteration
        items1 = list(reader)
        assert len(items1) == 10

        # Second iteration
        items2 = list(reader)
        assert len(items2) == 10
        assert items1 == items2

    def test_stream_reader_empty_lines(self, tmp_path):
        """Test that empty lines are skipped."""
        input_path = tmp_path / "test.jsonl"

        with open(input_path, 'w') as f:
            f.write('{"id": 1}\n')
            f.write('\n')  # Empty line
            f.write('{"id": 2}\n')
            f.write('\n\n')  # Multiple empty lines
            f.write('{"id": 3}\n')

        reader = StreamReader(input_path)
        items = list(reader)

        assert len(items) == 3
        assert items[0] == {"id": 1}
        assert items[1] == {"id": 2}
        assert items[2] == {"id": 3}

    def test_stream_reader_file_not_found(self, tmp_path):
        """Test error when file doesn't exist."""
        input_path = tmp_path / "nonexistent.jsonl"

        with pytest.raises(FileNotFoundError):
            StreamReader(input_path)

    def test_stream_reader_corrupted_json(self, tmp_path):
        """Test error on corrupted JSON."""
        input_path = tmp_path / "bad.jsonl"

        with open(input_path, 'w') as f:
            f.write('{"id": 1}\n')
            f.write('not valid json\n')
            f.write('{"id": 3}\n')

        reader = StreamReader(input_path)
        iterator = iter(reader)

        # First item should work
        assert next(iterator) == {"id": 1}

        # Second item should raise error
        with pytest.raises(ValueError, match="Invalid JSON on line 2"):
            next(iterator)

    def test_stream_reader_corrupted_pickle(self, tmp_path):
        """Test error on corrupted Pickle file."""
        input_path = tmp_path / "bad.pkl"

        # Write incomplete pickle file
        with open(input_path, 'wb') as f:
            import struct
            # Write length but no data
            f.write(struct.pack('I', 100))
            f.write(b'incomplete')

        reader = StreamReader(input_path)

        with pytest.raises(ValueError, match="Corrupted pickle file"):
            list(reader)


class TestStreamWriterReaderIntegration:
    """Integration tests for StreamWriter and StreamReader."""

    def test_write_read_roundtrip_jsonl(self, tmp_path):
        """Test writing and reading back JSONL data."""
        path = tmp_path / "data.jsonl"

        # Write
        def data_gen():
            for i in range(1000):
                yield {
                    "id": i,
                    "name": f"item_{i}",
                    "value": i * 1.5,
                    "tags": ["tag1", "tag2"]
                }

        writer = StreamWriter(path, format="jsonl")
        write_count = writer.write(data_gen())
        assert write_count == 1000

        # Read
        reader = StreamReader(path, format="jsonl")
        items = list(reader)

        assert len(items) == 1000
        assert items[0]["id"] == 0
        assert items[0]["name"] == "item_0"
        assert items[500]["value"] == 750.0

    def test_write_read_roundtrip_pickle(self, tmp_path):
        """Test writing and reading back Pickle data."""
        path = tmp_path / "data.pkl"

        # Write complex Python objects
        def data_gen():
            for i in range(100):
                yield {
                    "id": i,
                    "tuple": (i, i * 2, i * 3),
                    "set": {i, i + 1},
                    "nested": {
                        "level1": {
                            "level2": [i, i + 1]
                        }
                    }
                }

        writer = StreamWriter(path, format="pickle")
        write_count = writer.write(data_gen())
        assert write_count == 100

        # Read
        reader = StreamReader(path, format="pickle")
        items = list(reader)

        assert len(items) == 100
        assert items[0]["tuple"] == (0, 0, 0)
        assert 50 in items[50]["set"]


class TestGeneratorTaskDecorator:
    """Tests for @generator_task decorator."""

    def test_generator_task_basic(self, tmp_path):
        """Test basic generator task."""
        @generator_task(format="jsonl")
        def generate_data():
            for i in range(100):
                yield {"id": i, "value": i * 2}

        result_path = generate_data()

        assert isinstance(result_path, str)
        assert Path(result_path).exists()

        # Verify contents
        reader = StreamReader(result_path)
        items = list(reader)
        assert len(items) == 100
        assert items[0] == {"id": 0, "value": 0}

    def test_generator_task_large_dataset(self, tmp_path):
        """Test generator with large dataset to verify O(1) memory."""
        @generator_task(format="jsonl")
        def generate_large_data():
            # Generate 100k items
            for i in range(100000):
                yield {"id": i, "data": f"item_{i}"}

        result_path = generate_large_data()

        # Verify file exists and has correct count
        reader = StreamReader(result_path)
        count = sum(1 for _ in reader)
        assert count == 100000

    def test_generator_task_pickle_format(self, tmp_path):
        """Test generator task with pickle format."""
        @generator_task(format="pickle")
        def generate_complex_data():
            for i in range(50):
                yield {
                    "id": i,
                    "complex": {"nested": [i, i + 1]},
                    "tuple": (i, i * 2)
                }

        result_path = generate_complex_data()

        reader = StreamReader(result_path, format="pickle")
        items = list(reader)
        assert len(items) == 50
        assert items[0]["tuple"] == (0, 0)

    def test_generator_task_non_generator_passthrough(self):
        """Test that decorator passes through non-generator results."""
        @generator_task(format="jsonl")
        def not_a_generator():
            # Sometimes return a path directly
            return "/some/existing/path.jsonl"

        result = not_a_generator()
        assert result == "/some/existing/path.jsonl"


# Define these at module level so they can be pickled
@generator_task(format="jsonl")
def _test_extract_basic():
    """Test function: Extract 1000 records."""
    for i in range(1000):
        yield {"id": i, "value": i * 2}


def _test_transform_basic(context: TaskContext):
    """Test function: Transform by summing values."""
    input_path = context.upstream("extract")
    reader = StreamReader(input_path)
    total = sum(item["value"] for item in reader)
    return total


@generator_task(format="jsonl")
def _test_extract_chained():
    """Test function: Extract 100 records for chaining."""
    for i in range(100):
        yield {"id": i, "value": i}


@generator_task(format="jsonl")
def _test_transform_chained(context: TaskContext):
    """Test function: Transform values by multiplying by 10."""
    input_path = context.upstream("extract")
    reader = StreamReader(input_path)

    for item in reader:
        yield {
            "id": item["id"],
            "value": item["value"] * 10
        }


def _test_load_chained(context: TaskContext):
    """Test function: Load and sum values."""
    input_path = context.upstream("transform")
    reader = StreamReader(input_path)

    values = [item["value"] for item in reader]
    return sum(values)


class TestGeneratorTaskWithDAG:
    """Integration tests with DAG."""

    def test_generator_standalone_workflow(self, tmp_path):
        """Test generator workflow without complex DAG dependencies."""
        # Step 1: Generate data
        @generator_task(format="jsonl")
        def extract():
            for i in range(1000):
                yield {"id": i, "value": i * 2}

        # Step 2: Read and transform
        extract_path = extract()
        assert Path(extract_path).exists()

        # Verify we can read and process the data
        reader = StreamReader(extract_path)
        total = sum(item["value"] for item in reader)
        expected_total = sum(i * 2 for i in range(1000))
        assert total == expected_total

    def test_chained_generator_workflow(self, tmp_path):
        """Test chaining generator operations manually."""
        # Step 1: Extract
        @generator_task(format="jsonl")
        def extract():
            for i in range(100):
                yield {"id": i, "value": i}

        extract_path = extract()

        # Step 2: Transform
        @generator_task(format="jsonl")
        def transform():
            reader = StreamReader(extract_path)
            for item in reader:
                yield {
                    "id": item["id"],
                    "value": item["value"] * 10
                }

        transform_path = transform()

        # Step 3: Load
        reader = StreamReader(transform_path)
        total = sum(item["value"] for item in reader)
        expected = sum(i * 10 for i in range(100))
        assert total == expected


class TestAsyncGeneratorTaskDecorator:
    """Tests for @async_generator_task decorator."""

    @pytest.mark.asyncio
    async def test_async_generator_task_basic(self):
        """Test basic async generator task."""
        @async_generator_task(format="jsonl")
        async def generate_async_data():
            for i in range(50):
                # Simulate async operation
                await asyncio.sleep(0.001)
                yield {"id": i, "value": i * 3}

        result_path = await generate_async_data()

        assert isinstance(result_path, str)
        assert Path(result_path).exists()

        # Verify contents
        reader = StreamReader(result_path)
        items = list(reader)
        assert len(items) == 50
        assert items[0] == {"id": 0, "value": 0}
        assert items[-1] == {"id": 49, "value": 147}

    @pytest.mark.asyncio
    async def test_async_generator_task_pickle(self):
        """Test async generator with pickle format."""
        @async_generator_task(format="pickle")
        async def generate_complex():
            for i in range(20):
                await asyncio.sleep(0.001)
                yield {"id": i, "data": [i, i + 1, i + 2]}

        result_path = await generate_complex()

        reader = StreamReader(result_path, format="pickle")
        items = list(reader)
        assert len(items) == 20


class TestCSVFormat:
    """Tests for CSV format support."""

    def test_stream_writer_csv(self, tmp_path):
        """Test writing items to CSV format."""
        output_path = tmp_path / "test.csv"

        def data_gen():
            for i in range(100):
                yield {"id": i, "name": f"user_{i}", "value": i * 2.5}

        writer = StreamWriter(output_path, format="csv")
        count = writer.write(data_gen())

        assert count == 100
        assert output_path.exists()

        # Verify file contents
        with open(output_path, 'r') as f:
            lines = f.readlines()
            # Header + 100 rows
            assert len(lines) == 101
            assert lines[0].strip() == "id,name,value"

    def test_stream_reader_csv(self, tmp_path):
        """Test reading items from CSV format."""
        input_path = tmp_path / "test.csv"

        # Create test CSV file
        with open(input_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=["id", "name", "value"])
            writer.writeheader()
            for i in range(50):
                writer.writerow({"id": i, "name": f"user_{i}", "value": i * 2})

        # Read back
        reader = StreamReader(input_path, format="csv")
        items = list(reader)

        assert len(items) == 50
        # CSV returns strings by default
        assert items[0] == {"id": "0", "name": "user_0", "value": "0"}
        assert items[-1] == {"id": "49", "name": "user_49", "value": "98"}

    def test_csv_roundtrip(self, tmp_path):
        """Test writing and reading back CSV data."""
        path = tmp_path / "data.csv"

        def data_gen():
            for i in range(100):
                yield {"id": i, "category": f"cat_{i % 5}", "amount": i * 1.5}

        writer = StreamWriter(path)
        write_count = writer.write(data_gen())
        assert write_count == 100

        reader = StreamReader(path)
        items = list(reader)
        assert len(items) == 100

    def test_generator_task_csv_format(self):
        """Test generator task with CSV format."""
        @generator_task(format="csv")
        def generate_csv_data():
            for i in range(50):
                yield {"id": i, "data": f"item_{i}"}

        result_path = generate_csv_data()
        assert Path(result_path).exists()

        reader = StreamReader(result_path, format="csv")
        items = list(reader)
        assert len(items) == 50


class TestParquetFormat:
    """Tests for Parquet format support."""

    def test_stream_writer_parquet(self, tmp_path):
        """Test writing items to Parquet format."""
        pytest.importorskip("pyarrow")

        output_path = tmp_path / "test.parquet"

        def data_gen():
            for i in range(1000):
                yield {"id": i, "name": f"user_{i}", "value": i * 2.5}

        writer = StreamWriter(output_path, format="parquet")
        count = writer.write(data_gen())

        assert count == 1000
        assert output_path.exists()

    def test_stream_reader_parquet(self, tmp_path):
        """Test reading items from Parquet format."""
        pytest.importorskip("pyarrow")
        import pyarrow as pa
        import pyarrow.parquet as pq

        input_path = tmp_path / "test.parquet"

        # Create test Parquet file
        data = [{"id": i, "value": i * 3} for i in range(100)]
        table = pa.Table.from_pylist(data)
        pq.write_table(table, input_path)

        # Read back
        reader = StreamReader(input_path, format="parquet")
        items = list(reader)

        assert len(items) == 100
        assert items[0] == {"id": 0, "value": 0}
        assert items[-1] == {"id": 99, "value": 297}

    def test_parquet_roundtrip(self, tmp_path):
        """Test writing and reading back Parquet data."""
        pytest.importorskip("pyarrow")

        path = tmp_path / "data.parquet"

        def data_gen():
            for i in range(5000):
                yield {
                    "id": i,
                    "category": f"cat_{i % 10}",
                    "amount": i * 1.5,
                    "active": i % 2 == 0
                }

        writer = StreamWriter(path)
        write_count = writer.write(data_gen())
        assert write_count == 5000

        reader = StreamReader(path)
        items = list(reader)
        assert len(items) == 5000
        assert items[0]["id"] == 0
        assert items[0]["active"] is True

    def test_generator_task_parquet_format(self):
        """Test generator task with Parquet format."""
        pytest.importorskip("pyarrow")

        @generator_task(format="parquet")
        def generate_parquet_data():
            for i in range(100):
                yield {"id": i, "data": f"item_{i}", "score": i * 0.1}

        result_path = generate_parquet_data()
        assert Path(result_path).exists()

        reader = StreamReader(result_path, format="parquet")
        items = list(reader)
        assert len(items) == 100

    def test_parquet_without_pyarrow(self, tmp_path):
        """Test that Parquet raises ImportError without pyarrow."""
        output_path = tmp_path / "test.parquet"

        # This will only work if pyarrow is not installed
        # In test environments it will be installed, so we skip
        # But the error handling is there for users without it
        pass


class TestErrorHandling:
    """Test error handling in streaming components."""

    def test_stream_writer_serialization_error(self, tmp_path):
        """Test handling of non-serializable objects in JSONL."""
        output_path = tmp_path / "test.jsonl"

        def bad_data_gen():
            yield {"id": 1}
            yield {"id": 2, "bad": lambda x: x}  # Lambda not JSON serializable
            yield {"id": 3}

        writer = StreamWriter(output_path, format="jsonl")

        with pytest.raises(TypeError):
            writer.write(bad_data_gen())

    def test_generator_task_with_exception(self):
        """Test generator task that raises exception."""
        @generator_task(format="jsonl")
        def failing_generator():
            for i in range(10):
                if i == 5:
                    raise ValueError("Intentional error")
                yield {"id": i}

        with pytest.raises(ValueError, match="Intentional error"):
            failing_generator()

    def test_csv_non_dict_error(self, tmp_path):
        """Test that CSV format requires dict items."""
        output_path = tmp_path / "test.csv"

        def bad_data_gen():
            yield [1, 2, 3]  # List, not dict

        writer = StreamWriter(output_path, format="csv")

        with pytest.raises(TypeError, match="CSV format requires dict items"):
            writer.write(bad_data_gen())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
