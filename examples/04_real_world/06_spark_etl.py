from pathlib import Path
import json
import uuid

from queuack import (
    DAG, 
    DuckQueue, 
    TaskContext, 
    streaming_task,
)

RESULTS_DIR = Path(__file__).parent / "results_spark"
RESULTS_DIR.mkdir(exist_ok=True)

_SPARK = None

def startup():
    global _SPARK
    if _SPARK is None:
        from pyspark.sql import SparkSession
        _SPARK = (
            SparkSession.builder
            .master("local[*]")
            .appName("queuack-minimal")
            .config("spark.ui.enabled", "false")
            .getOrCreate()
        )

@streaming_task
def extract():
    output = RESULTS_DIR / f"extract_{uuid.uuid4().hex[:8]}.jsonl"
    with open(output, "w", encoding="utf-8") as f:
        for i in range(10_000):
            print(json.dumps({"id": i, "value": i * 2}), file=f)

    return str(output)

@streaming_task
def transform(context: TaskContext):
    input_path = context.upstream("extract")
    # Context auto-closed by decorator
    
    output = RESULTS_DIR / f"transform_{uuid.uuid4().hex[:8]}.jsonl"
    
    df = _SPARK.read.json(input_path)
    df_filtered = df.filter(df.value > 100)
    
    tmp_dir = str(output) + ".tmp"
    df_filtered.write.mode("overwrite").json(tmp_dir)
    
    # Consolidate
    import glob, shutil
    with open(output, "w") as out:
        for part in sorted(glob.glob(f"{tmp_dir}/part-*.json")):
            with open(part) as f:
                out.write(f.read())
    shutil.rmtree(tmp_dir)
    
    return str(output)

@streaming_task
def load(context: TaskContext):
    input_path = context.upstream("transform")
    # Context auto-closed
    
    count = total = 0
    with open(input_path) as f:
        for line in f:
            row = json.loads(line)
            count += 1
            total += row["value"]
    
    return {"count": count, "avg": total / count}

def create_dag_etl(queue: DuckQueue) -> DAG:
    dag = DAG("etl", queue)

    dag.add_node(extract, name="extract")
    dag.add_node(transform, name="transform", depends_on="extract")
    dag.add_node(load, name="load", depends_on="transform")

    return dag

def teardown(context: TaskContext):
    if _SPARK:
        _SPARK.stop()

if __name__ == "__main__":
    # Clean, expressive API
    with DAG("spark_etl").with_timing() as dag:
        etl_dag = DAG("ETL Pipeline")

        dag.add_node(startup, name="startup")
        dag.add_node(create_dag_etl, name="etl_subdag", depends_on='startup')
        dag.add_node(teardown, name="teardown", depends_on="etl_subdag")

        success = dag.execute()
    
    if success:
        result = dag.get_job("load")
        if result and result.result:
            import pickle
            stats = pickle.loads(result.result)
            print(f"\nFinal: {stats}")
    
