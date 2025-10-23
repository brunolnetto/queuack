# Queuack → Airflow Parity Assessment & Implementation Roadmap

**Goal:** Transform Queuack from a basic job queue into an Airflow-like workflow orchestration system while maintaining its lightweight, single-file database philosophy.

---

## 📊 Feature Comparison Matrix

| Feature | Airflow | Queuack Current | Gap Severity | Implementation Effort |
|---------|---------|-----------------|--------------|----------------------|
| **Core Scheduling** |
| Cron/Interval Scheduling | ✅ `@daily`, `@hourly` | ❌ Manual enqueue only | 🔴 Critical | Medium |
| Start/End Dates | ✅ Full support | ❌ None | 🟡 High | Low |
| Catchup/Backfill | ✅ Automatic | ❌ None | 🟡 High | High |
| Timezone Support | ✅ Per-DAG | ❌ None | 🟢 Medium | Low |
| **DAG Definition** |
| Context Manager API | ✅ `with DAG()` | ✅ `with queue.dag()` | ✅ Complete | - |
| Dependency Operators | ✅ `task1 >> task2` | ❌ String refs only | 🟡 High | Low |
| Task Groups | ✅ Nested groups | ❌ Flat only | 🟢 Medium | Medium |
| Dynamic Task Generation | ✅ `.expand()` | ⚠️ Manual loops | 🟡 High | Medium |
| **Execution & State** |
| Rich Task States | ✅ 10+ states | ⚠️ 6 states | 🟡 High | Low |
| Task Instance Tracking | ✅ Per run | ✅ Via `dag_run_id` | ✅ Complete | - |
| XCom (Data Passing) | ✅ Built-in | ❌ None | 🔴 Critical | Medium |
| Execution Context | ✅ Rich context | ❌ No context | 🔴 Critical | Medium |
| **Retry & Recovery** |
| Exponential Backoff | ✅ Configurable | ❌ Fixed retries | 🟡 High | Low |
| Retry Delay | ✅ Per-task | ❌ Immediate | 🟡 High | Low |
| Task Timeout | ✅ Per-task | ✅ Per-task | ✅ Complete | - |
| **Triggers & Sensors** |
| Trigger Rules | ✅ 8+ rules | ⚠️ ALL/ANY only | 🟡 High | Low |
| Sensors | ✅ Many types | ❌ None | 🟡 High | High |
| External Triggers | ✅ API/CLI | ❌ None | 🔴 Critical | Medium |
| **Observability** |
| CLI Management | ✅ Comprehensive | ⚠️ Basic stats | 🔴 Critical | Medium |
| Task Logs | ✅ Per-task storage | ❌ None | 🟡 High | Medium |
| DAG Visualization | ✅ Web UI | ⚠️ Mermaid only | 🟢 Medium | - |
| Metrics/Monitoring | ✅ Rich metrics | ⚠️ Basic stats | 🟢 Medium | Medium |
| **Resource Management** |
| Pools/Slots | ✅ Per-resource | ❌ None | 🟡 High | High |
| Priority Weights | ✅ Per-task | ✅ Per-task | ✅ Complete | - |
| Concurrency Limits | ✅ DAG-level | ⚠️ Worker-level | 🟢 Medium | Medium |
| **Alerting & Callbacks** |
| Email Alerts | ✅ Built-in | ❌ None | 🟡 High | Medium |
| Custom Callbacks | ✅ 5+ hooks | ❌ None | 🟡 High | Low |
| SLA Monitoring | ✅ Per-task | ❌ None | 🟢 Medium | Medium |

**Legend:**
- 🔴 Critical: Blocks Airflow-like experience
- 🟡 High: Significantly impacts usability
- 🟢 Medium: Nice-to-have for feature parity

---

## 🎯 Phase 1: Core Scheduling (Weeks 1-2)

### 1.1 Schedule Specification

**Current State:**
```python
# Manual enqueue only
with queue.dag("etl") as dag:
    extract = dag.enqueue(extract_data, name="extract")
```

**Target State:**
```python
from queuack import DuckQueue, Schedule

queue = DuckQueue("queue.db")

# Declarative scheduling
@queue.scheduled_dag(
    name="daily_etl",
    schedule=Schedule.daily(hour=2, minute=30),  # 02:30 UTC
    start_date="2024-01-01",
    catchup=False
)
def daily_etl():
    with queue.dag("daily_etl") as dag:
        extract = dag.enqueue(extract_data, name="extract")
        transform = dag.enqueue(transform_data, name="transform", depends_on="extract")
    return dag
```

**Implementation Plan:**

```python
# queuack/schedule.py
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Callable
import croniter

@dataclass
class Schedule:
    """Schedule specification for DAG runs."""
    
    # Cron expression or interval
    schedule_type: str  # 'cron', 'interval', 'once'
    cron_expression: Optional[str] = None
    interval: Optional[timedelta] = None
    
    start_date: datetime = None
    end_date: Optional[datetime] = None
    timezone: str = "UTC"
    
    @classmethod
    def cron(cls, expression: str, **kwargs):
        """Schedule using cron expression."""
        return cls(schedule_type='cron', cron_expression=expression, **kwargs)
    
    @classmethod
    def daily(cls, hour: int = 0, minute: int = 0, **kwargs):
        """Daily at specific time."""
        return cls.cron(f"{minute} {hour} * * *", **kwargs)
    
    @classmethod
    def hourly(cls, minute: int = 0, **kwargs):
        """Every hour."""
        return cls.cron(f"{minute} * * * *", **kwargs)
    
    @classmethod
    def interval(cls, days=0, hours=0, minutes=0, **kwargs):
        """Fixed interval."""
        return cls(
            schedule_type='interval',
            interval=timedelta(days=days, hours=hours, minutes=minutes),
            **kwargs
        )
    
    def get_next_run(self, after: datetime) -> Optional[datetime]:
        """Calculate next run time after given datetime."""
        if self.end_date and after >= self.end_date:
            return None
        
        if self.schedule_type == 'cron':
            cron = croniter.croniter(self.cron_expression, after)
            next_run = cron.get_next(datetime)
            return next_run if not self.end_date or next_run <= self.end_date else None
        
        elif self.schedule_type == 'interval':
            next_run = after + self.interval
            return next_run if not self.end_date or next_run <= self.end_date else None
        
        return None


# queuack/scheduler.py
class DAGScheduler:
    """Background scheduler that triggers DAGs based on schedules."""
    
    def __init__(self, queue: DuckQueue):
        self.queue = queue
        self.scheduled_dags: Dict[str, Tuple[Callable, Schedule]] = {}
        self._running = False
        self._thread = None
    
    def register_dag(self, name: str, dag_factory: Callable, schedule: Schedule):
        """Register a DAG with its schedule."""
        self.scheduled_dags[name] = (dag_factory, schedule)
        
        # Persist schedule to database
        with self.queue._db_lock:
            self.queue.conn.execute("""
                INSERT OR REPLACE INTO dag_schedules 
                (name, schedule_type, cron_expression, interval_seconds, 
                 start_date, end_date, timezone, last_run, next_run)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """, [
                name,
                schedule.schedule_type,
                schedule.cron_expression,
                schedule.interval.total_seconds() if schedule.interval else None,
                schedule.start_date,
                schedule.end_date,
                schedule.timezone,
                schedule.get_next_run(datetime.now())
            ])
    
    def start(self):
        """Start scheduler background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self._thread.start()
    
    def stop(self):
        """Stop scheduler."""
        self._running = False
        if self._thread:
            self._thread.join()
    
    def _run_scheduler(self):
        """Main scheduler loop."""
        while self._running:
            now = datetime.now()
            
            with self.queue._db_lock:
                # Find DAGs that need to run
                results = self.queue.conn.execute("""
                    SELECT name, next_run FROM dag_schedules
                    WHERE next_run <= ? AND (end_date IS NULL OR end_date > ?)
                """, [now, now]).fetchall()
                
                for name, next_run_str in results:
                    if name not in self.scheduled_dags:
                        continue
                    
                    # Trigger DAG
                    dag_factory, schedule = self.scheduled_dags[name]
                    self._trigger_dag(name, dag_factory, schedule)
                    
                    # Update next run
                    next_run = schedule.get_next_run(datetime.fromisoformat(next_run_str))
                    self.queue.conn.execute("""
                        UPDATE dag_schedules
                        SET last_run = ?, next_run = ?
                        WHERE name = ?
                    """, [now, next_run, name])
            
            time.sleep(30)  # Check every 30 seconds
    
    def _trigger_dag(self, name: str, dag_factory: Callable, schedule: Schedule):
        """Execute DAG factory to create and submit DAG."""
        try:
            dag = dag_factory()
            dag.submit()
            logger.info(f"Scheduled DAG '{name}' triggered successfully")
        except Exception as e:
            logger.error(f"Failed to trigger DAG '{name}': {e}")


# Add to DuckQueue
class DuckQueue:
    def __init__(self, *args, **kwargs):
        # ... existing init
        self._scheduler = DAGScheduler(self)
    
    def scheduled_dag(self, name: str, schedule: Schedule, start_date: str = None, 
                     catchup: bool = False):
        """Decorator for scheduled DAGs."""
        if start_date:
            schedule.start_date = datetime.fromisoformat(start_date)
        
        def decorator(dag_factory: Callable):
            self._scheduler.register_dag(name, dag_factory, schedule)
            return dag_factory
        
        return decorator
    
    def start_scheduler(self):
        """Start background scheduler."""
        self._scheduler.start()
```

**Database Schema Changes:**
```sql
CREATE TABLE dag_schedules (
    name VARCHAR PRIMARY KEY,
    schedule_type VARCHAR NOT NULL,
    cron_expression VARCHAR,
    interval_seconds REAL,
    start_date TIMESTAMP NOT NULL,
    end_date TIMESTAMP,
    timezone VARCHAR DEFAULT 'UTC',
    last_run TIMESTAMP,
    next_run TIMESTAMP,
    enabled BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_dag_schedules_next_run ON dag_schedules(next_run);
```

**Effort:** Medium (3-4 days)
**Dependencies:** `croniter` library

---

## 🎯 Phase 2: XCom & Execution Context (Weeks 2-3)

### 2.1 XCom (Cross-Communication)

**Current State:**
```python
# No way to pass data between tasks
def extract():
    return {"users": [1, 2, 3]}  # Lost!

def transform():
    users = ???  # Can't access extract's result
```

**Target State:**
```python
def extract(**context):
    data = {"users": [1, 2, 3]}
    context['task_instance'].xcom_push(key='users', value=data)
    return data  # Also auto-pushed as return value

def transform(**context):
    users = context['task_instance'].xcom_pull(task_ids='extract', key='return_value')
    # Or explicit key
    users = context['task_instance'].xcom_pull(task_ids='extract', key='users')
    return process(users)
```

**Implementation Plan:**

```python
# queuack/xcom.py
import pickle
import json
from typing import Any, Optional

class XComManager:
    """Manages inter-task communication."""
    
    def __init__(self, queue: DuckQueue):
        self.queue = queue
    
    def push(self, dag_run_id: str, task_id: str, key: str, value: Any) -> str:
        """Store value in XCom."""
        xcom_id = str(uuid.uuid4())
        
        # Serialize value
        try:
            serialized = json.dumps(value)
            serialization_type = 'json'
        except (TypeError, ValueError):
            serialized = pickle.dumps(value)
            serialization_type = 'pickle'
        
        with self.queue._db_lock:
            self.queue.conn.execute("""
                INSERT INTO xcom (id, dag_run_id, task_id, key, value, 
                                 serialization_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, [
                xcom_id, dag_run_id, task_id, key, 
                serialized, serialization_type, datetime.now()
            ])
        
        return xcom_id
    
    def pull(self, dag_run_id: str, task_ids: Union[str, List[str]], 
             key: str = 'return_value') -> Any:
        """Retrieve value from XCom."""
        if isinstance(task_ids, str):
            task_ids = [task_ids]
        
        with self.queue._db_lock:
            placeholders = ','.join(['?' for _ in task_ids])
            result = self.queue.conn.execute(f"""
                SELECT value, serialization_type FROM xcom
                WHERE dag_run_id = ? AND task_id IN ({placeholders}) AND key = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, [dag_run_id] + task_ids + [key]).fetchone()
        
        if not result:
            return None
        
        value, serialization_type = result
        
        if serialization_type == 'json':
            return json.loads(value)
        else:
            return pickle.loads(value)
    
    def clear(self, dag_run_id: str, task_id: Optional[str] = None):
        """Clear XCom values."""
        with self.queue._db_lock:
            if task_id:
                self.queue.conn.execute(
                    "DELETE FROM xcom WHERE dag_run_id = ? AND task_id = ?",
                    [dag_run_id, task_id]
                )
            else:
                self.queue.conn.execute(
                    "DELETE FROM xcom WHERE dag_run_id = ?",
                    [dag_run_id]
                )


# queuack/context.py
@dataclass
class TaskInstance:
    """Execution context for a single task."""
    job_id: str
    dag_run_id: str
    task_id: str
    execution_date: datetime
    xcom_manager: XComManager
    
    def xcom_push(self, key: str, value: Any) -> str:
        """Push value to XCom."""
        return self.xcom_manager.push(self.dag_run_id, self.task_id, key, value)
    
    def xcom_pull(self, task_ids: Union[str, List[str]], 
                  key: str = 'return_value') -> Any:
        """Pull value from XCom."""
        return self.xcom_manager.pull(self.dag_run_id, task_ids, key)


@dataclass
class ExecutionContext:
    """Full execution context passed to tasks."""
    task_instance: TaskInstance
    dag_run_id: str
    execution_date: datetime
    dag_name: str
    task_id: str
    attempt: int
    
    # Convenience shortcuts
    @property
    def ti(self):
        return self.task_instance
    
    def to_dict(self):
        """Convert to dict for **context unpacking."""
        return {
            'task_instance': self.task_instance,
            'ti': self.task_instance,
            'dag_run_id': self.dag_run_id,
            'execution_date': self.execution_date,
            'dag_name': self.dag_name,
            'task_id': self.task_id,
            'attempt': self.attempt
        }


# Modified Job execution
@dataclass
class Job:
    # ... existing fields
    
    def execute(self, context: Optional[ExecutionContext] = None) -> Any:
        """Execute with optional context."""
        func = pickle.loads(self.func)
        args = pickle.loads(self.args)
        kwargs = pickle.loads(self.kwargs)
        
        # Inject context if function accepts **context
        if context:
            import inspect
            sig = inspect.signature(func)
            
            # Check if function has **kwargs or explicit context params
            if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                kwargs.update(context.to_dict())
            elif 'context' in sig.parameters:
                kwargs['context'] = context
        
        result = func(*args, **kwargs)
        
        # Auto-push return value to XCom
        if context and result is not None:
            context.task_instance.xcom_push('return_value', result)
        
        return result
```

**Database Schema Changes:**
```sql
CREATE TABLE xcom (
    id VARCHAR PRIMARY KEY,
    dag_run_id VARCHAR NOT NULL,
    task_id VARCHAR NOT NULL,
    key VARCHAR NOT NULL,
    value BLOB NOT NULL,
    serialization_type VARCHAR DEFAULT 'pickle',
    created_at TIMESTAMP NOT NULL,
    UNIQUE(dag_run_id, task_id, key)
);

CREATE INDEX idx_xcom_dag_run ON xcom(dag_run_id);
CREATE INDEX idx_xcom_task ON xcom(dag_run_id, task_id);
```

**Effort:** Medium (4-5 days)

---

## 🎯 Phase 3: Enhanced CLI & Observability (Week 4)

### 3.1 Comprehensive CLI

**Target Commands:**
```bash
# DAG management
queuack dags list
queuack dags show my_dag
queuack dags trigger my_dag --conf '{"key": "value"}'
queuack dags pause my_dag
queuack dags unpause my_dag
queuack dags delete my_dag

# DAG runs
queuack dags list-runs my_dag
queuack dags run-state my_dag <run_id>
queuack dags backfill my_dag --start 2024-01-01 --end 2024-01-31

# Tasks
queuack tasks list my_dag
queuack tasks state my_dag <run_id> <task_id>
queuack tasks logs my_dag <run_id> <task_id>
queuack tasks clear my_dag <task_id>  # Retry

# Workers
queuack workers list
queuack workers start --concurrency 4
queuack workers stop <worker_id>

# Scheduler
queuack scheduler start
queuack scheduler status
```

**Implementation:**

```python
# queuack/cli.py
import click
from tabulate import tabulate

@click.group()
@click.option('--db', default='queue.db', envvar='QUEUACK_DB')
@click.pass_context
def cli(ctx, db):
    """Queuack - Lightweight workflow orchestration."""
    ctx.ensure_object(dict)
    ctx.obj['queue'] = DuckQueue(db)


@cli.group()
def dags():
    """DAG management commands."""
    pass


@dags.command('list')
@click.pass_context
def list_dags(ctx):
    """List all DAGs."""
    queue = ctx.obj['queue']
    
    with queue._db_lock:
        results = queue.conn.execute("""
            SELECT DISTINCT name, description, 
                   COUNT(*) as runs,
                   MAX(created_at) as last_run
            FROM dag_runs
            GROUP BY name, description
            ORDER BY last_run DESC
        """).fetchall()
    
    table = [[r[0], r[1], r[2], r[3]] for r in results]
    click.echo(tabulate(
        table,
        headers=['DAG', 'Description', 'Runs', 'Last Run'],
        tablefmt='grid'
    ))


@dags.command('trigger')
@click.argument('dag_name')
@click.option('--conf', help='JSON config')
@click.option('--wait', is_flag=True, help='Wait for completion')
@click.pass_context
def trigger_dag(ctx, dag_name, conf, wait):
    """Manually trigger a DAG run."""
    queue = ctx.obj['queue']
    
    # Parse config
    config = {}
    if conf:
        import json
        config = json.loads(conf)
    
    # Find DAG factory and trigger
    if hasattr(queue._scheduler, 'scheduled_dags') and dag_name in queue._scheduler.scheduled_dags:
        dag_factory, _ = queue._scheduler.scheduled_dags[dag_name]
        dag = dag_factory()
        run_id = dag.submit()
        
        click.echo(f"✓ Triggered DAG '{dag_name}' (run_id: {run_id})")
        
        if wait:
            from queuack.dag_context import DAGRun
            dag_run = DAGRun(queue, run_id)
            
            import time
            while not dag_run.is_complete():
                progress = dag_run.get_progress()
                click.echo(f"Progress: {progress}")
                time.sleep(2)
            
            click.echo(f"✓ DAG completed: {dag_run.get_status()}")
    else:
        click.echo(f"❌ DAG '{dag_name}' not found", err=True)


@dags.command('show')
@click.argument('dag_name')
@click.pass_context
def show_dag(ctx, dag_name):
    """Show DAG structure."""
    queue = ctx.obj['queue']
    
    # Get latest DAG run
    with queue._db_lock:
        result = queue.conn.execute("""
            SELECT id FROM dag_runs
            WHERE name = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, [dag_name]).fetchone()
    
    if not result:
        click.echo(f"❌ No runs found for DAG '{dag_name}'", err=True)
        return
    
    dag_run_id = result[0]
    
    # Get tasks
    with queue._db_lock:
        tasks = queue.conn.execute("""
            SELECT node_name, status, dependencies.parent_job_id
            FROM jobs
            LEFT JOIN job_dependencies dependencies ON jobs.id = dependencies.child_job_id
            WHERE dag_run_id = ?
        """, [dag_run_id]).fetchall()
    
    # Build dependency graph
    click.echo(f"\nDAG: {dag_name}")
    click.echo("="*60)
    
    for task_name, status, parent in tasks:
        indent = "  " if parent else ""
        status_icon = {
            'done': '✓',
            'failed': '✗',
            'pending': '○',
            'claimed': '◐',
            'skipped': '⊗'
        }.get(status, '?')
        
        click.echo(f"{indent}{status_icon} {task_name} [{status}]")


@cli.group()
def tasks():
    """Task management commands."""
    pass


@tasks.command('logs')
@click.argument('dag_name')
@click.argument('run_id')
@click.argument('task_id')
@click.pass_context
def task_logs(ctx, dag_name, run_id, task_id):
    """Show task execution logs."""
    queue = ctx.obj['queue']
    
    with queue._db_lock:
        result = queue.conn.execute("""
            SELECT logs FROM job_logs
            WHERE dag_run_id = ? AND node_name = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, [run_id, task_id]).fetchone()
    
    if result:
        click.echo(result[0])
    else:
        click.echo("No logs found")


@cli.group()
def workers():
    """Worker management commands."""
    pass


@workers.command('start')
@click.option('--concurrency', default=4)
@click.pass_context
def start_worker(ctx, concurrency):
    """Start a worker process."""
    queue = ctx.obj['queue']
    from queuack import Worker
    
    click.echo(f"Starting worker (concurrency={concurrency})...")
    worker = Worker(queue, concurrency=concurrency)
    worker.run()


@cli.group()
def scheduler():
    """Scheduler management commands."""
    pass


@scheduler.command('start')
@click.pass_context
def start_scheduler(ctx):
    """Start the scheduler."""
    queue = ctx.obj['queue']
    
    click.echo("Starting scheduler...")
    queue.start_scheduler()
    
    # Keep running
    import signal
    import time
    
    def handler(sig, frame):
        click.echo("\nStopping scheduler...")
        queue._scheduler.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
    
    while True:
        time.sleep(1)


if __name__ == '__main__':
    cli()
```

**Effort:** Medium (3-4 days)

---

## 🎯 Phase 4: Dependency Operators & Syntactic Sugar (Week 5)

### 4.1 `>>` and `<<` Operators

**Target State:**
```python
with queue.dag("pipeline") as dag:
    extract = dag.task(extract_data, name="extract")
    transform = dag.task(transform_data, name="transform")
    load = dag.task(load_data, name="load")
    
    # Airflow-style chaining
    extract >> transform >> load
    
    # Or fan-out
    extract >> [transform1, transform2] >> load
    
    # Or fan-in
    [extract1, extract2] >> merge >> load
```

**Implementation:**

```python
# queuack/task.py
class Task:
    """Wrapper for task that supports >> operator."""
    
    def __init__(self, dag_context: DAGContext, func: Callable, 
                 name: str, **kwargs):
        self.dag = dag_context
        self.func = func
        self.name = name
        self.kwargs = kwargs
        self.job_id = None
        self._dependencies = []
    
    def __rshift__(self, other):
        """Implement >> operator (self >> other)."""
        if isinstance(other, list):
            for task in other:
                task.set_upstream(self)
            return other
        else:
            other.set_upstream(self)
            return other
    
    def __lshift__(self, other):
        """Implement << operator (self << other)."""
        if isinstance(other, list):
            for task in other:
                self.set_upstream(task)
            return self
        else:
            self.set_upstream(other)
            return self
    
    def set_upstream(self, task):
        """Add upstream dependency."""
        if isinstance(task, Task):
            self._dependencies.append(task.name)
        else:
            self._dependencies.append(task)
    
    def set_downstream(self, task):
        """Add downstream dependency (reverse of upstream)."""
        if isinstance(task, Task):
            task.set_upstream(self)
        else:
            task.set_upstream(self.name)
    
    def submit(self):
        """Actually enqueue the task."""
        if not self.job_id:
            self.job_id = self.dag.enqueue(
                self.func,
                name=self.name,
                depends_on=self._dependencies if self._dependencies else None,
                **self.kwargs
            )
        return self.job_id


# Modified DAGContext
class DAGContext:
    def task(self, func: Callable, name: str = None, **kwargs) -> Task:
        """Create a Task object (lazy enqueue)."""
        if name is None:
            name = func.__name__
        
        return Task(self, func, name, **kwargs)
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """On exit, submit all tasks in dependency order."""
        if exc_type is None and not self._submitted:
            # Build execution graph from Task dependencies
            for task_name, task in self._tasks.items():
                task.submit()
            
            # Continue with normal submission
            super().__exit__(exc_type, exc_val, exc_tb)
```

**Effort:** Low (1-2 days)

---

## 🎯 Phase 5: Sensors & Advanced Triggers (Week 6)

### 5.1 Sensor Framework

**Target State:**
```python
from queuack.sensors import FileSensor, TimeSensor, ExternalTaskSensor

with queue.dag("wait_for_data") as dag:
    # Wait for file to exist
    wait_file = FileSensor(
        name="wait_for_file",
        filepath="/data/input.csv",
        timeout=3600,  # 1 hour
        poke_interval=60  # Check every minute
    )
    
    # Wait for specific time
    wait_time = TimeSensor(
        name="wait_until_9am",
        target_time="09:00:00"
    )
    
    # Wait for external task
    wait_upstream = ExternalTaskSensor(
        name="wait_upstream",
        external_dag_id="upstream_dag",
        external_task_id="export_data"
    )
    
    process = dag.task(process_data, name="process")
    
    [wait_file, wait_time, wait_upstream] >> process
```

**Implementation:**

```python
# queuack/sensors.py
from abc import ABC, abstractmethod
import time
from pathlib import Path

class BaseSensor(ABC):
    """Base class for all sensors."""
    
    def __init__(self, name: str, timeout: int = 3600, 
                 poke_interval: int = 60, mode: str = 'poke'):
        """
        Args:
            name: Sensor task name
            timeout: Maximum time to wait (seconds)
            poke_interval: Time between checks (seconds)
            mode: 'poke' (blocking) or 'reschedule' (release worker)
        """
        self.name = name
        self.timeout = timeout
        self.poke_interval = poke_interval
        self.mode = mode
    
    @abstractmethod
    def poke(self, context) -> bool:
        """Check if condition is met. Return True when ready."""
        pass
    
    def execute(self, **context):
        """Execute sensor logic."""
        start_time = time.time()
        
        while True:
            elapsed = time.time() - start_time
            
            if elapsed > self.timeout:
                raise TimeoutError(f"Sensor {self.name} timed out after {self.timeout}s")
            
            # Check condition
            if self.poke(context):
                return True
            
            # Wait before next check
            if self.mode == 'poke':
                time.sleep(self.poke_interval)
            else:
                # Reschedule mode: release worker and requeue
                raise SensorRescheduleException(self.poke_interval)


class FileSensor(BaseSensor):
    """Wait for file to exist."""
    
    def __init__(self, filepath: str, **kwargs):
        super().__init__(**kwargs)
        self.filepath = Path(filepath)
    
    def poke(self, context) -> bool:
        exists = self.filepath.exists()
        if exists:
            logger.info(f"File {self.filepath} found!")
        return exists


class TimeSensor(BaseSensor):
    """Wait until specific time."""
    
    def __init__(self, target_time: str, **kwargs):
        super().__init__(**kwargs)
        # Parse HH:MM:SS
        parts = target_time.split(':')
        self.target_hour = int(parts[0])
        self.target_minute = int(parts[1]) if len(parts) > 1 else 0
        self.target_second = int(parts[2]) if len(parts) > 2 else 0
    
    def poke(self, context) -> bool:
        now = datetime.now()
        target = now.replace(
            hour=self.target_hour,
            minute=self.target_minute,
            second=self.target_second,
            microsecond=0
        )
        
        # If target time passed today, wait for tomorrow
        if now > target:
            target += timedelta(days=1)
        
        return now >= target


class ExternalTaskSensor(BaseSensor):
    """Wait for external DAG task to complete."""
    
    def __init__(self, external_dag_id: str, external_task_id: str, 
                 queue: DuckQueue, **kwargs):
        super().__init__(**kwargs)
        self.external_dag_id = external_dag_id
        self.external_task_id = external_task_id
        self.queue = queue
    
    def poke(self, context) -> bool:
        with self.queue._db_lock:
            result = self.queue.conn.execute("""
                SELECT status FROM jobs
                WHERE dag_run_id IN (
                    SELECT id FROM dag_runs 
                    WHERE name = ?
                    ORDER BY created_at DESC 
                    LIMIT 1
                )
                AND node_name = ?
            """, [self.external_dag_id, self.external_task_id]).fetchone()
        
        if result and result[0] == 'done':
            logger.info(f"External task {self.external_dag_id}.{self.external_task_id} completed")
            return True
        
        return False


class SensorRescheduleException(Exception):
    """Raised to reschedule sensor instead of blocking."""
    
    def __init__(self, delay: int):
        self.delay = delay
        super().__init__(f"Reschedule after {delay}s")


# Integration with DAGContext
class DAGContext:
    def sensor(self, sensor: BaseSensor, **kwargs) -> Task:
        """Add sensor as a task."""
        return self.task(sensor.execute, name=sensor.name, **kwargs)
```

**Effort:** High (5-6 days)

---

## 🎯 Phase 6: Retry Logic & Callbacks (Week 7)

### 6.1 Exponential Backoff & Callbacks

**Target State:**
```python
from queuack import RetryPolicy

def send_email_on_failure(context):
    """Callback on task failure."""
    task = context['task_instance']
    print(f"Task {task.task_id} failed on attempt {context['attempt']}")
    # Send email, Slack notification, etc.

with queue.dag("resilient_pipeline") as dag:
    flaky_task = dag.task(
        flaky_api_call,
        name="api_call",
        retry_policy=RetryPolicy(
            max_attempts=5,
            initial_delay=60,  # 1 minute
            max_delay=3600,    # 1 hour
            backoff_factor=2.0,  # Exponential
            retry_on=[requests.RequestException, TimeoutError]
        ),
        on_failure_callback=send_email_on_failure,
        on_success_callback=lambda ctx: print("Success!"),
        on_retry_callback=lambda ctx: print(f"Retry #{ctx['attempt']}")
    )
```

**Implementation:**

```python
# queuack/retry.py
@dataclass
class RetryPolicy:
    """Retry configuration."""
    max_attempts: int = 3
    initial_delay: int = 60  # seconds
    max_delay: int = 3600
    backoff_factor: float = 2.0  # Exponential
    retry_on: List[type] = None  # Exception types to retry
    
    def get_delay(self, attempt: int) -> int:
        """Calculate delay for given attempt."""
        if attempt <= 0:
            return 0
        
        delay = self.initial_delay * (self.backoff_factor ** (attempt - 1))
        return min(int(delay), self.max_delay)
    
    def should_retry(self, exception: Exception) -> bool:
        """Check if exception is retryable."""
        if not self.retry_on:
            return True  # Retry all exceptions
        
        return any(isinstance(exception, exc_type) for exc_type in self.retry_on)


# Modified Job execution
@dataclass
class Job:
    # Add new fields
    retry_policy: Optional[RetryPolicy] = None
    on_success_callback: Optional[Callable] = None
    on_failure_callback: Optional[Callable] = None
    on_retry_callback: Optional[Callable] = None
    
    def execute(self, context: Optional[ExecutionContext] = None) -> Any:
        """Execute with retry logic and callbacks."""
        func = pickle.loads(self.func)
        args = pickle.loads(self.args)
        kwargs = pickle.loads(self.kwargs)
        
        # Inject context
        if context:
            import inspect
            sig = inspect.signature(func)
            if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                kwargs.update(context.to_dict())
        
        try:
            result = func(*args, **kwargs)
            
            # Success callback
            if self.on_success_callback and context:
                self.on_success_callback(context.to_dict())
            
            # Auto-push to XCom
            if context and result is not None:
                context.task_instance.xcom_push('return_value', result)
            
            return result
        
        except Exception as e:
            # Check if should retry
            if self.retry_policy and self.attempts < self.retry_policy.max_attempts:
                if self.retry_policy.should_retry(e):
                    # Retry callback
                    if self.on_retry_callback and context:
                        self.on_retry_callback(context.to_dict())
                    
                    # Calculate delay
                    delay = self.retry_policy.get_delay(self.attempts)
                    
                    raise RetryException(delay, str(e))
            
            # Failure callback
            if self.on_failure_callback and context:
                try:
                    self.on_failure_callback(context.to_dict())
                except Exception as cb_error:
                    logger.error(f"Callback error: {cb_error}")
            
            raise


class RetryException(Exception):
    """Signal that task should be retried."""
    def __init__(self, delay: int, original_error: str):
        self.delay = delay
        self.original_error = original_error
        super().__init__(f"Retry after {delay}s: {original_error}")


# Modified Worker to handle RetryException
class Worker:
    def _execute_job(self, job: Job, job_num: int):
        """Execute with retry handling."""
        try:
            # Build context
            context = self._build_context(job)
            result = job.execute(context=context)
            self.queue.ack(job.id, result=result)
            
        except RetryException as e:
            # Requeue with delay
            logger.info(f"Job {job.id[:8]} retry #{job.attempts} in {e.delay}s")
            
            self.queue.conn.execute("""
                UPDATE jobs
                SET 
                    status = 'delayed',
                    execute_after = ?,
                    error = ?,
                    claimed_at = NULL,
                    claimed_by = NULL
                WHERE id = ?
            """, [datetime.now() + timedelta(seconds=e.delay), e.original_error, job.id])
        
        except Exception as e:
            # Permanent failure
            error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            self.queue.ack(job.id, error=error_msg)
    
    def _build_context(self, job: Job) -> ExecutionContext:
        """Build execution context for job."""
        return ExecutionContext(
            task_instance=TaskInstance(
                job_id=job.id,
                dag_run_id=job.dag_run_id,
                task_id=job.node_name,
                execution_date=job.created_at,
                xcom_manager=self.queue._xcom_manager
            ),
            dag_run_id=job.dag_run_id,
            execution_date=job.created_at,
            dag_name=job.dag_run_id,  # TODO: Store actual DAG name
            task_id=job.node_name,
            attempt=job.attempts
        )
```

**Database Schema Changes:**
```sql
ALTER TABLE jobs ADD COLUMN retry_policy_json TEXT;
ALTER TABLE jobs ADD COLUMN callbacks_json TEXT;
```

**Effort:** Medium (3-4 days)

---

## 🎯 Phase 7: Pools & Resource Management (Week 8)

### 7.1 Resource Pools

**Target State:**
```python
from queuack import Pool

# Define resource pools
queue.create_pool('gpu', slots=2, description='GPU resources')
queue.create_pool('api_rate_limit', slots=10, description='API calls per minute')

with queue.dag("ml_training") as dag:
    # Task requires GPU slot
    train = dag.task(
        train_model,
        name="train",
        pool='gpu',  # Blocks until GPU available
        priority_weight=10
    )
    
    # Multiple API calls share rate limit pool
    for i in range(20):
        api_call = dag.task(
            call_api,
            name=f"api_{i}",
            pool='api_rate_limit'  # Max 10 concurrent
        )
```

**Implementation:**

```python
# queuack/pools.py
@dataclass
class Pool:
    """Resource pool with limited slots."""
    name: str
    slots: int
    description: str = ""
    occupied_slots: int = 0
    
    def has_capacity(self) -> bool:
        return self.occupied_slots < self.slots
    
    def acquire(self) -> bool:
        if self.has_capacity():
            self.occupied_slots += 1
            return True
        return False
    
    def release(self):
        if self.occupied_slots > 0:
            self.occupied_slots -= 1


class PoolManager:
    """Manages resource pools."""
    
    def __init__(self, queue: DuckQueue):
        self.queue = queue
        self._pools: Dict[str, Pool] = {}
        self._load_pools()
    
    def create_pool(self, name: str, slots: int, description: str = ""):
        """Create or update a pool."""
        with self.queue._db_lock:
            self.queue.conn.execute("""
                INSERT OR REPLACE INTO pools (name, slots, description)
                VALUES (?, ?, ?)
            """, [name, slots, description])
        
        self._pools[name] = Pool(name, slots, description)
    
    def get_pool(self, name: str) -> Optional[Pool]:
        """Get pool by name."""
        return self._pools.get(name)
    
    def _load_pools(self):
        """Load pools from database."""
        with self.queue._db_lock:
            results = self.queue.conn.execute("""
                SELECT name, slots, description FROM pools
            """).fetchall()
        
        for name, slots, desc in results:
            self._pools[name] = Pool(name, slots, desc)
    
    def can_claim(self, pool_name: str) -> bool:
        """Check if pool has capacity."""
        pool = self._pools.get(pool_name)
        if not pool:
            return True  # No pool restriction
        
        with self.queue._db_lock:
            # Count jobs using this pool
            result = self.queue.conn.execute("""
                SELECT COUNT(*) FROM jobs
                WHERE pool = ? AND status = 'claimed'
            """, [pool_name]).fetchone()
            
            occupied = result[0] if result else 0
            return occupied < pool.slots


# Modified claim logic in DuckQueue
class DuckQueue:
    def claim(self, queue: str = None, worker_id: str = None, 
              claim_timeout: int = 300) -> Optional[Job]:
        """Claim with pool awareness."""
        queue = queue or self.default_queue
        worker_id = worker_id or self._generate_worker_id()
        now = datetime.now()
        
        with self._db_lock:
            # Promote delayed jobs
            self.conn.execute("""
                UPDATE jobs SET status = 'pending'
                WHERE status = 'delayed' AND execute_after <= ?
            """, [now])
            
            # Atomic claim with pool check
            result = self.conn.execute("""
                UPDATE jobs
                SET 
                    status = 'claimed',
                    claimed_at = ?,
                    claimed_by = ?,
                    attempts = attempts + 1
                WHERE id = (
                    SELECT j.id FROM jobs AS j
                    WHERE j.queue = ?
                    AND (j.status = 'pending' OR (j.status = 'claimed' AND j.claimed_at < ?))
                    AND j.attempts < j.max_attempts
                    AND (j.execute_after IS NULL OR j.execute_after <= ?)
                    AND (
                        -- Pool check
                        j.pool IS NULL OR j.pool IN (
                            SELECT name FROM pools p
                            WHERE (
                                SELECT COUNT(*) FROM jobs 
                                WHERE pool = p.name AND status = 'claimed'
                            ) < p.slots
                        )
                    )
                    AND (
                        -- Dependency check (existing logic)
                        NOT EXISTS (SELECT 1 FROM job_dependencies WHERE child_job_id = j.id)
                        OR (j.dependency_mode = 'all' AND NOT EXISTS (...))
                        OR (j.dependency_mode = 'any' AND EXISTS (...))
                    )
                    ORDER BY j.priority DESC, j.created_at ASC
                    LIMIT 1
                )
                RETURNING *
            """, [now, worker_id, queue, now - timedelta(seconds=claim_timeout), now]).fetchone()
            
            # ... rest of claim logic
```

**Database Schema Changes:**
```sql
CREATE TABLE pools (
    name VARCHAR PRIMARY KEY,
    slots INTEGER NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE jobs ADD COLUMN pool VARCHAR REFERENCES pools(name);
CREATE INDEX idx_jobs_pool ON jobs(pool, status);
```

**Effort:** Medium (4-5 days)

---

## 🎯 Phase 8: Task Logs & Monitoring (Week 9)

### 8.1 Task-Level Logging

**Target State:**
```python
def my_task(**context):
    logger = context['task_instance'].get_logger()
    
    logger.info("Starting task")
    logger.warning("This is a warning")
    logger.error("This is an error")
    
    # Logs automatically captured and stored per task
```

**Implementation:**

```python
# queuack/logging.py
import logging
import io
from contextlib import redirect_stdout, redirect_stderr

class TaskLogger:
    """Logger that captures task output."""
    
    def __init__(self, job_id: str, task_id: str, dag_run_id: str, queue: DuckQueue):
        self.job_id = job_id
        self.task_id = task_id
        self.dag_run_id = dag_run_id
        self.queue = queue
        
        # Create logger
        self.logger = logging.getLogger(f"queuack.task.{task_id}")
        self.logger.setLevel(logging.INFO)
        
        # Capture to string buffer
        self.log_buffer = io.StringIO()
        handler = logging.StreamHandler(self.log_buffer)
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        self.logger.addHandler(handler)
    
    def get_logs(self) -> str:
        """Get captured logs."""
        return self.log_buffer.getvalue()
    
    def save_logs(self):
        """Persist logs to database."""
        logs = self.get_logs()
        
        with self.queue._db_lock:
            self.queue.conn.execute("""
                INSERT INTO job_logs (job_id, dag_run_id, node_name, logs, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, [self.job_id, self.dag_run_id, self.task_id, logs, datetime.now()])


# Modified TaskInstance
@dataclass
class TaskInstance:
    # ... existing fields
    _logger: Optional[TaskLogger] = None
    
    def get_logger(self) -> logging.Logger:
        """Get task-specific logger."""
        if not self._logger:
            self._logger = TaskLogger(
                self.job_id,
                self.task_id,
                self.dag_run_id,
                self.xcom_manager.queue
            )
        return self._logger.logger


# Modified Job execution
class Job:
    def execute(self, context: Optional[ExecutionContext] = None) -> Any:
        """Execute with log capture."""
        func = pickle.loads(self.func)
        args = pickle.loads(self.args)
        kwargs = pickle.loads(self.kwargs)
        
        # Setup logger
        if context:
            task_logger = context.task_instance.get_logger()
            
            # Redirect stdout/stderr
            stdout_buffer = io.StringIO()
            stderr_buffer = io.StringIO()
            
            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                try:
                    # Inject context
                    if any(p.kind == inspect.Parameter.VAR_KEYWORD 
                           for p in inspect.signature(func).parameters.values()):
                        kwargs.update(context.to_dict())
                    
                    task_logger.info(f"Executing {self.node_name}")
                    result = func(*args, **kwargs)
                    task_logger.info(f"Completed {self.node_name}")
                    
                    # Save logs
                    context.task_instance._logger.save_logs()
                    
                    return result
                
                except Exception as e:
                    task_logger.error(f"Failed: {e}")
                    context.task_instance._logger.save_logs()
                    raise
```

**Database Schema Changes:**
```sql
CREATE TABLE job_logs (
    id VARCHAR PRIMARY KEY DEFAULT (uuid()),
    job_id VARCHAR NOT NULL,
    dag_run_id VARCHAR,
    node_name VARCHAR,
    logs TEXT,
    created_at TIMESTAMP NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE INDEX idx_job_logs_job ON job_logs(job_id);
CREATE INDEX idx_job_logs_dag_run ON job_logs(dag_run_id, node_name);
```

**Effort:** Medium (3-4 days)

---

## 🎯 Phase 9: Backfill & Historical Execution (Week 10)

### 9.1 Backfill Mechanism

**Target State:**
```bash
# Backfill DAG for date range
queuack dags backfill my_dag \
    --start-date 2024-01-01 \
    --end-date 2024-01-31 \
    --clear  # Clear existing runs first
```

**Implementation:**

```python
# queuack/backfill.py
class BackfillRunner:
    """Handles backfilling DAGs for historical dates."""
    
    def __init__(self, queue: DuckQueue):
        self.queue = queue
    
    def backfill(
        self,
        dag_name: str,
        start_date: datetime,
        end_date: datetime,
        clear: bool = False,
        max_active_runs: int = 1
    ):
        """Backfill DAG for date range."""
        
        # Get DAG factory
        if dag_name not in self.queue._scheduler.scheduled_dags:
            raise ValueError(f"DAG '{dag_name}' not found")
        
        dag_factory, schedule = self.queue._scheduler.scheduled_dags[dag_name]
        
        # Clear existing runs if requested
        if clear:
            self._clear_runs(dag_name, start_date, end_date)
        
        # Generate execution dates
        execution_dates = self._generate_execution_dates(schedule, start_date, end_date)
        
        logger.info(f"Backfilling {len(execution_dates)} runs for {dag_name}")
        
        # Execute each date
        active_runs = []
        for exec_date in execution_dates:
            # Wait if too many active
            while len(active_runs) >= max_active_runs:
                active_runs = [r for r in active_runs if not r.is_complete()]
                time.sleep(5)
            
            # Trigger DAG with execution_date
            dag = dag_factory()
            
            # Override execution date in context
            dag._execution_date = exec_date
            run_id = dag.submit()
            
            active_runs.append(DAGRun(self.queue, run_id))
            logger.info(f"Started backfill run for {exec_date}")
        
        # Wait for all to complete
        for run in active_runs:
            while not run.is_complete():
                time.sleep(5)
        
        logger.info(f"Backfill complete for {dag_name}")
    
    def _clear_runs(self, dag_name: str, start_date: datetime, end_date: datetime):
        """Clear existing runs in date range."""
        with self.queue._db_lock:
            self.queue.conn.execute("""
                DELETE FROM jobs
                WHERE dag_run_id IN (
                    SELECT id FROM dag_runs
                    WHERE name = ?
                    AND created_at BETWEEN ? AND ?
                )
            """, [dag_name, start_date, end_date])
            
            self.queue.conn.execute("""
                DELETE FROM dag_runs
                WHERE name = ? AND created_at BETWEEN ? AND ?
            """, [dag_name, start_date, end_date])
    
    def _generate_execution_dates(
        self,
        schedule: Schedule,
        start_date: datetime,
        end_date: datetime
    ) -> List[datetime]:
        """Generate list of execution dates."""
        dates = []
        current = start_date
        
        while current <= end_date:
            dates.append(current)
            next_date = schedule.get_next_run(current)
            
            if not next_date or next_date <= current:
                break
            
            current = next_date
        
        return dates


# Add to CLI
@dags.command('backfill')
@click.argument('dag_name')
@click.option('--start-date', required=True)
@click.option('--end-date', required=True)
@click.option('--clear', is_flag=True)
@click.option('--max-active-runs', default=1)
@click.pass_context
def backfill_dag(ctx, dag_name, start_date, end_date, clear, max_active_runs):
    """Backfill DAG for date range."""
    queue = ctx.obj['queue']
    
    start = datetime.fromisoformat(start_date)
    end = datetime.fromisoformat(end_date)
    
    runner = BackfillRunner(queue)
    runner.backfill(dag_name, start, end, clear, max_active_runs)
```

**Effort:** High (5-6 days)

---

## 📋 Implementation Priority Matrix

| Phase | Feature | User Impact | Technical Complexity | Dependencies | Recommended Order |
|-------|---------|-------------|---------------------|--------------|-------------------|
| 1 | Scheduling | 🔴 Critical | Medium | croniter | **1st** |
| 2 | XCom | 🔴 Critical | Medium | - | **2nd** |
| 2 | Context | 🔴 Critical | Medium | XCom | **2nd** |
| 3 | CLI | 🔴 Critical | Low | - | **3rd** |
| 4 | `>>` Operator | 🟡 High | Low | - | **4th** |
| 6 | Retry Logic | 🟡 High | Medium | - | **5th** |
| 5 | Sensors | 🟡 High | High | Context | **6th** |
| 7 | Pools | 🟡 High | High | - | **7th** |
| 8 | Logging | 🟡 High | Medium | Context | **8th** |
| 9 | Backfill | 🟢 Medium | High | Scheduling | **9th** |

---

## 🚀 Suggested Implementation Sequence

### **Sprint 1 (Weeks 1-3): Core Foundation**
1. ✅ Scheduling framework
2. ✅ XCom + Execution Context
3. ✅ Enhanced CLI

**Deliverable:** Scheduled DAGs with data passing

### **Sprint 2 (Weeks 4-6): Developer Experience**
4. ✅ `>>` operator & syntactic sugar
5. ✅ Retry policies with callbacks
6. ✅ Sensor framework

**Deliverable:** Airflow-like DAG authoring

### **Sprint 3 (Weeks 7-10): Production Features**
7. ✅ Resource pools
8. ✅ Task logging
9. ✅ Backfill mechanism

**Deliverable:** Production-ready orchestration

---

## 📦 Additional Dependencies

```toml
# pyproject.toml additions
[dependencies]
croniter = "^2.0.0"  # Cron scheduling
click = "^8.1.0"     # CLI
tabulate = "^0.9.0"  # CLI tables
colorama = "^0.4.0"  # Colored output
```

---

## 🎓 Migration Path for Existing Users

### Step 1: Backward Compatibility
All existing code continues to work:
```python
# Old API still works
with queue.dag("etl") as dag:
    extract = dag.enqueue(extract_data, name="extract")
```

### Step 2: Gradual Adoption
New features are opt-in:
```python
# Add scheduling when ready
@queue.scheduled_dag("etl", schedule=Schedule.daily())
def etl_dag():
    with queue.dag("etl") as dag:
        extract = dag.enqueue(extract_data, name="extract")
    return dag
```

### Step 3: Full Migration
Eventually adopt all features:
```python
@queue.scheduled_dag("etl", schedule=Schedule.daily())
def etl_dag():
    with queue.dag("etl") as dag:
        extract = dag.task(extract_data, name="extract")
        transform = dag.task(transform_data, name="transform")
        
        extract >> transform  # New syntax
    return dag
```

---

## 🧪 Testing Strategy

### Unit Tests
- Each component tested in isolation
- Mock database for fast tests
- Property-based testing for schedule calculations

### Integration Tests
- End-to-end DAG execution
- Scheduler correctness
- XCom data flow
- Retry behavior

### Performance Tests
- Benchmark scheduling overhead
- Pool contention scenarios
- Large DAG execution (100+ tasks)

---

## 📊 Success Metrics

| Metric | Current | Target | How to Measure |
|--------|---------|--------|----------------|
| Lines to define DAG | ~15 | ~10 | Code samples |
| Time to first DAG run | Manual | <5 min | Onboarding test |
| Scheduling accuracy | N/A | ±30s | Schedule deviation |
| XCom throughput | N/A | 1000 msg/s | Benchmark |
| Task retry latency | Fixed | Configurable | Retry tests |
| CLI command coverage | 20% | 80% | Command count |

---

## 🎯 Final Assessment

**Current State:** Queuack is a solid job queue with basic DAG support

**Target State:** Airflow-like orchestration without the complexity

**Gap:** ~10 weeks of focused development across 9 phases

**Biggest Wins:**
1. 🔴 Scheduling → Enables autonomous workflows
2. 🔴 XCom → Enables data pipelines
3. 🔴 Context → Enables task introspection
4. 🟡 CLI → Enables operational management

**Recommended Path:**
- Start with **Phase 1-3** (4 weeks) → 80% of Airflow DX
- Add **Phase 4-6** (3 weeks) → Feature parity
- Polish with **Phase 7-9** (3 weeks) → Production ready

This would give Queuack **90% of Airflow's functionality** while keeping the lightweight, single-file philosophy.

---

## 🎯 Phase 10: Advanced Features & Polish (Weeks 11-12)

### 10.1 Task Groups & SubDAGs

**Target State:**
```python
from queuack import TaskGroup

with queue.dag("complex_etl") as dag:
    # Group related tasks
    with TaskGroup("extract_sources", dag=dag) as extract_group:
        db_extract = dag.task(extract_db, name="db")
        api_extract = dag.task(extract_api, name="api")
        file_extract = dag.task(extract_file, name="file")
    
    with TaskGroup("transform", dag=dag) as transform_group:
        clean = dag.task(clean_data, name="clean")
        validate = dag.task(validate_data, name="validate")
        enrich = dag.task(enrich_data, name="enrich")
        
        clean >> validate >> enrich
    
    load = dag.task(load_data, name="load")
    
    # Groups can be chained
    extract_group >> transform_group >> load
```

**Implementation:**

```python
# queuack/task_group.py
class TaskGroup:
    """Logical grouping of tasks for organization."""
    
    def __init__(self, group_id: str, dag: DAGContext, prefix_group_id: bool = True):
        self.group_id = group_id
        self.dag = dag
        self.prefix_group_id = prefix_group_id
        self.tasks: List[Task] = []
        self._context_stack = []
        
        # Register with DAG
        if not hasattr(dag, '_task_groups'):
            dag._task_groups = {}
        dag._task_groups[group_id] = self
    
    def __enter__(self):
        """Enter group context."""
        # Store current group context
        if hasattr(self.dag, '_current_group'):
            self._context_stack.append(self.dag._current_group)
        
        self.dag._current_group = self
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit group context."""
        # Restore previous group context
        if self._context_stack:
            self.dag._current_group = self._context_stack.pop()
        else:
            self.dag._current_group = None
    
    def add_task(self, task: Task):
        """Add task to group."""
        self.tasks.append(task)
        
        # Prefix task name with group ID
        if self.prefix_group_id:
            task.name = f"{self.group_id}.{task.name}"
    
    def __rshift__(self, other):
        """Group >> Group or Group >> Task."""
        if isinstance(other, TaskGroup):
            # Connect all tasks in self to all tasks in other
            for self_task in self.tasks:
                for other_task in other.tasks:
                    self_task >> other_task
            return other
        else:
            # Connect all tasks in group to single task
            for task in self.tasks:
                task >> other
            return other
    
    def __lshift__(self, other):
        """Group << Group or Group << Task."""
        if isinstance(other, TaskGroup):
            for other_task in other.tasks:
                for self_task in self.tasks:
                    other_task >> self_task
            return self
        else:
            for task in self.tasks:
                other >> task
            return self


# Modified DAGContext to support groups
class DAGContext:
    def task(self, func: Callable, name: str = None, **kwargs) -> Task:
        """Create task, respecting current group context."""
        if name is None:
            name = func.__name__
        
        task = Task(self, func, name, **kwargs)
        
        # Add to current group if in group context
        if hasattr(self, '_current_group') and self._current_group:
            self._current_group.add_task(task)
        
        return task
```

---

### 10.2 SLA Monitoring

**Target State:**
```python
from datetime import timedelta
from queuack import SLA

def sla_miss_callback(dag_name, task_id, execution_date, **context):
    """Called when task misses SLA."""
    send_alert(f"SLA MISS: {dag_name}.{task_id}")

with queue.dag("sla_monitored", sla_miss_callback=sla_miss_callback) as dag:
    critical_task = dag.task(
        process_data,
        name="critical",
        sla=timedelta(minutes=30)  # Must complete in 30 minutes
    )
```

**Implementation:**

```python
# queuack/sla.py
class SLAMonitor:
    """Monitors task SLAs and triggers callbacks."""
    
    def __init__(self, queue: DuckQueue):
        self.queue = queue
        self._running = False
        self._thread = None
    
    def start(self):
        """Start SLA monitoring thread."""
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
    
    def stop(self):
        """Stop monitoring."""
        self._running = False
        if self._thread:
            self._thread.join()
    
    def _monitor_loop(self):
        """Check for SLA misses."""
        while self._running:
            now = datetime.now()
            
            with self.queue._db_lock:
                # Find tasks that missed SLA
                missed = self.queue.conn.execute("""
                    SELECT 
                        j.id, j.node_name, j.dag_run_id, j.sla_seconds,
                        j.claimed_at, j.created_at, dr.name as dag_name
                    FROM jobs j
                    JOIN dag_runs dr ON j.dag_run_id = dr.id
                    WHERE j.status IN ('claimed', 'pending')
                    AND j.sla_seconds IS NOT NULL
                    AND (
                        (j.claimed_at IS NOT NULL AND 
                         CAST((julianday(?) - julianday(j.claimed_at)) * 86400 AS INTEGER) > j.sla_seconds)
                        OR
                        (j.claimed_at IS NULL AND 
                         CAST((julianday(?) - julianday(j.created_at)) * 86400 AS INTEGER) > j.sla_seconds)
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM sla_misses 
                        WHERE job_id = j.id
                    )
                """, [now, now]).fetchall()
                
                for (job_id, task_id, dag_run_id, sla_seconds, 
                     claimed_at, created_at, dag_name) in missed:
                    
                    # Record SLA miss
                    self.queue.conn.execute("""
                        INSERT INTO sla_misses 
                        (job_id, dag_run_id, task_id, dag_name, 
                         sla_seconds, detected_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, [job_id, dag_run_id, task_id, dag_name, sla_seconds, now])
                    
                    # Trigger callback
                    self._trigger_sla_callback(
                        dag_name, task_id, created_at, dag_run_id
                    )
            
            time.sleep(60)  # Check every minute
    
    def _trigger_sla_callback(self, dag_name, task_id, execution_date, dag_run_id):
        """Execute SLA miss callback."""
        # Look up DAG's SLA callback
        if hasattr(self.queue._scheduler, 'scheduled_dags'):
            if dag_name in self.queue._scheduler.scheduled_dags:
                dag_factory, schedule = self.queue._scheduler.scheduled_dags[dag_name]
                
                # Check if DAG has SLA callback
                if hasattr(dag_factory, '__sla_miss_callback__'):
                    callback = dag_factory.__sla_miss_callback__
                    try:
                        callback(
                            dag_name=dag_name,
                            task_id=task_id,
                            execution_date=execution_date,
                            dag_run_id=dag_run_id
                        )
                    except Exception as e:
                        logger.error(f"SLA callback error: {e}")


# Database schema
"""
CREATE TABLE sla_misses (
    id VARCHAR PRIMARY KEY DEFAULT (uuid()),
    job_id VARCHAR NOT NULL,
    dag_run_id VARCHAR,
    task_id VARCHAR NOT NULL,
    dag_name VARCHAR NOT NULL,
    sla_seconds INTEGER NOT NULL,
    detected_at TIMESTAMP NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

ALTER TABLE jobs ADD COLUMN sla_seconds INTEGER;
CREATE INDEX idx_sla_misses_dag ON sla_misses(dag_run_id);
"""
```

---

### 10.3 Trigger Rules (Advanced Dependency Logic)

**Target State:**
```python
from queuack import TriggerRule

with queue.dag("resilient_pipeline") as dag:
    tasks = []
    for i in range(5):
        task = dag.task(process_partition, args=(i,), name=f"partition_{i}")
        tasks.append(task)
    
    # Run even if some partitions fail
    aggregate = dag.task(
        aggregate_results,
        name="aggregate",
        trigger_rule=TriggerRule.ALL_DONE  # Wait for all, succeed or fail
    )
    
    # Run only if at least one succeeds
    publish = dag.task(
        publish_results,
        name="publish",
        trigger_rule=TriggerRule.ONE_SUCCESS
    )
    
    tasks >> aggregate >> publish
```

**Implementation:**

```python
# queuack/trigger_rules.py
from enum import Enum

class TriggerRule(Enum):
    """Task trigger rules."""
    ALL_SUCCESS = "all_success"      # All parents succeeded (default)
    ALL_FAILED = "all_failed"        # All parents failed
    ALL_DONE = "all_done"            # All parents done (success or failed)
    ONE_SUCCESS = "one_success"      # At least one parent succeeded
    ONE_FAILED = "one_failed"        # At least one parent failed
    NONE_FAILED = "none_failed"      # No parents failed (success or skipped)
    NONE_SKIPPED = "none_skipped"    # No parents skipped
    DUMMY = "dummy"                  # Always trigger


class TriggerRuleEvaluator:
    """Evaluates if task should run based on trigger rule."""
    
    @staticmethod
    def evaluate(
        trigger_rule: TriggerRule,
        parent_statuses: List[str]
    ) -> bool:
        """Check if trigger rule is satisfied."""
        
        if trigger_rule == TriggerRule.ALL_SUCCESS:
            return all(s == 'done' for s in parent_statuses)
        
        elif trigger_rule == TriggerRule.ALL_FAILED:
            return all(s == 'failed' for s in parent_statuses)
        
        elif trigger_rule == TriggerRule.ALL_DONE:
            return all(s in ('done', 'failed') for s in parent_statuses)
        
        elif trigger_rule == TriggerRule.ONE_SUCCESS:
            return any(s == 'done' for s in parent_statuses)
        
        elif trigger_rule == TriggerRule.ONE_FAILED:
            return any(s == 'failed' for s in parent_statuses)
        
        elif trigger_rule == TriggerRule.NONE_FAILED:
            return not any(s == 'failed' for s in parent_statuses)
        
        elif trigger_rule == TriggerRule.NONE_SKIPPED:
            return not any(s == 'skipped' for s in parent_statuses)
        
        elif trigger_rule == TriggerRule.DUMMY:
            return True
        
        return False


# Modified claim logic in DuckQueue
class DuckQueue:
    def claim(self, queue: str = None, worker_id: str = None, 
              claim_timeout: int = 300) -> Optional[Job]:
        """Claim with trigger rule awareness."""
        # ... existing setup
        
        with self._db_lock:
            result = self.conn.execute("""
                UPDATE jobs
                SET status = 'claimed', claimed_at = ?, claimed_by = ?, attempts = attempts + 1
                WHERE id = (
                    SELECT j.id FROM jobs AS j
                    WHERE j.queue = ?
                    AND (j.status = 'pending' OR ...)
                    AND (
                        -- No dependencies OR trigger rule satisfied
                        NOT EXISTS (SELECT 1 FROM job_dependencies WHERE child_job_id = j.id)
                        OR (
                            -- Evaluate trigger rule
                            CASE j.trigger_rule
                                WHEN 'all_success' THEN NOT EXISTS (
                                    SELECT 1 FROM job_dependencies jd
                                    JOIN jobs pj ON jd.parent_job_id = pj.id
                                    WHERE jd.child_job_id = j.id AND pj.status != 'done'
                                )
                                WHEN 'all_done' THEN NOT EXISTS (
                                    SELECT 1 FROM job_dependencies jd
                                    JOIN jobs pj ON jd.parent_job_id = pj.id
                                    WHERE jd.child_job_id = j.id 
                                    AND pj.status NOT IN ('done', 'failed')
                                )
                                WHEN 'one_success' THEN EXISTS (
                                    SELECT 1 FROM job_dependencies jd
                                    JOIN jobs pj ON jd.parent_job_id = pj.id
                                    WHERE jd.child_job_id = j.id AND pj.status = 'done'
                                )
                                -- Add other rules...
                                ELSE 1  -- Default: all_success
                            END
                        )
                    )
                    ORDER BY j.priority DESC, j.created_at ASC
                    LIMIT 1
                )
                RETURNING *
            """, [now, worker_id, queue, ...]).fetchone()
```

---

### 10.4 Email & Slack Alerts

**Target State:**
```python
from queuack.alerts import EmailAlert, SlackAlert

# Configure global alerts
queue.configure_alerts(
    email=EmailAlert(
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        from_addr="alerts@company.com",
        to_addrs=["team@company.com"]
    ),
    slack=SlackAlert(
        webhook_url="https://hooks.slack.com/services/XXX"
    )
)

with queue.dag("monitored_dag") as dag:
    critical = dag.task(
        critical_process,
        name="critical",
        on_failure_callback=[
            lambda ctx: queue.alerts.email.send_failure(ctx),
            lambda ctx: queue.alerts.slack.send_failure(ctx)
        ]
    )
```

**Implementation:**

```python
# queuack/alerts.py
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
from typing import Dict, Any

class EmailAlert:
    """Send email alerts."""
    
    def __init__(self, smtp_host: str, smtp_port: int, 
                 from_addr: str, to_addrs: List[str],
                 username: str = None, password: str = None):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.from_addr = from_addr
        self.to_addrs = to_addrs
        self.username = username
        self.password = password
    
    def send_failure(self, context: Dict[str, Any]):
        """Send task failure email."""
        task = context['task_instance']
        
        subject = f"❌ Task Failed: {context['dag_name']}.{context['task_id']}"
        
        body = f"""
Task Failure Alert

DAG: {context['dag_name']}
Task: {context['task_id']}
Execution Date: {context['execution_date']}
Attempt: {context['attempt']}

View logs: queuack tasks logs {context['dag_name']} {context['dag_run_id']} {context['task_id']}
"""
        
        self._send_email(subject, body)
    
    def send_sla_miss(self, dag_name: str, task_id: str, **kwargs):
        """Send SLA miss alert."""
        subject = f"⏰ SLA Missed: {dag_name}.{task_id}"
        body = f"Task {task_id} in DAG {dag_name} missed its SLA."
        self._send_email(subject, body)
    
    def _send_email(self, subject: str, body: str):
        """Send email via SMTP."""
        msg = MIMEMultipart()
        msg['From'] = self.from_addr
        msg['To'] = ', '.join(self.to_addrs)
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                if self.username and self.password:
                    server.login(self.username, self.password)
                server.send_message(msg)
            logger.info(f"Email sent: {subject}")
        except Exception as e:
            logger.error(f"Failed to send email: {e}")


class SlackAlert:
    """Send Slack alerts."""
    
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
    
    def send_failure(self, context: Dict[str, Any]):
        """Send task failure to Slack."""
        payload = {
            "text": f"❌ *Task Failed*",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"Task Failed: {context['task_id']}"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*DAG:*\n{context['dag_name']}"},
                        {"type": "mrkdwn", "text": f"*Task:*\n{context['task_id']}"},
                        {"type": "mrkdwn", "text": f"*Attempt:*\n{context['attempt']}"},
                        {"type": "mrkdwn", "text": f"*Time:*\n{context['execution_date']}"}
                    ]
                }
            ]
        }
        
        self._send_slack(payload)
    
    def send_sla_miss(self, dag_name: str, task_id: str, **kwargs):
        """Send SLA miss to Slack."""
        payload = {
            "text": f"⏰ *SLA Missed*: {dag_name}.{task_id}"
        }
        self._send_slack(payload)
    
    def _send_slack(self, payload: dict):
        """Send to Slack webhook."""
        try:
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info("Slack alert sent")
        except Exception as e:
            logger.error(f"Failed to send Slack alert: {e}")


class AlertManager:
    """Manages all alert channels."""
    
    def __init__(self):
        self.email: Optional[EmailAlert] = None
        self.slack: Optional[SlackAlert] = None
    
    def configure(self, email: EmailAlert = None, slack: SlackAlert = None):
        """Configure alert channels."""
        self.email = email
        self.slack = slack


# Add to DuckQueue
class DuckQueue:
    def __init__(self, *args, **kwargs):
        # ... existing init
        self.alerts = AlertManager()
    
    def configure_alerts(self, email: EmailAlert = None, slack: SlackAlert = None):
        """Configure alerting."""
        self.alerts.configure(email, slack)
```

---

## 📚 Complete Database Schema (All Phases)

```sql
-- Core jobs table (existing + enhancements)
CREATE TABLE jobs (
    id VARCHAR PRIMARY KEY,
    dag_run_id VARCHAR,
    node_name VARCHAR,
    dependency_mode VARCHAR DEFAULT 'all',
    func BLOB NOT NULL,
    args BLOB NOT NULL,
    kwargs BLOB NOT NULL,
    queue VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    priority INTEGER DEFAULT 50,
    created_at TIMESTAMP NOT NULL,
    execute_after TIMESTAMP,
    claimed_at TIMESTAMP,
    claimed_by VARCHAR,
    completed_at TIMESTAMP,
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    timeout_seconds INTEGER DEFAULT 300,
    result BLOB,
    error TEXT,
    skipped_at TIMESTAMP,
    skip_reason TEXT,
    skipped_by VARCHAR,
    
    -- Phase 6: Retry & Callbacks
    retry_policy_json TEXT,
    callbacks_json TEXT,
    
    -- Phase 7: Pools
    pool VARCHAR REFERENCES pools(name),
    
    -- Phase 10: SLA & Trigger Rules
    sla_seconds INTEGER,
    trigger_rule VARCHAR DEFAULT 'all_success'
);

-- Indexes
CREATE INDEX idx_jobs_claim ON jobs(queue, status, priority DESC, execute_after, created_at);
CREATE INDEX idx_jobs_dag_run ON jobs(dag_run_id);
CREATE INDEX idx_jobs_node_name ON jobs(node_name);
CREATE INDEX idx_jobs_pool ON jobs(pool, status);

-- Job dependencies
CREATE TABLE job_dependencies (
    child_job_id VARCHAR NOT NULL,
    parent_job_id VARCHAR NOT NULL,
    PRIMARY KEY (child_job_id, parent_job_id)
);

CREATE INDEX idx_job_dependencies_parent ON job_dependencies(parent_job_id);
CREATE INDEX idx_job_dependencies_child ON job_dependencies(child_job_id);

-- DAG runs
CREATE TABLE dag_runs (
    id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    description TEXT,
    created_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    status VARCHAR NOT NULL,
    metadata JSON,
    execution_date TIMESTAMP  -- Phase 9: Backfill support
);

CREATE INDEX idx_dag_runs_name ON dag_runs(name);
CREATE INDEX idx_dag_runs_status ON dag_runs(status);
CREATE INDEX idx_dag_runs_execution_date ON dag_runs(execution_date);

-- Phase 1: Scheduling
CREATE TABLE dag_schedules (
    name VARCHAR PRIMARY KEY,
    schedule_type VARCHAR NOT NULL,
    cron_expression VARCHAR,
    interval_seconds REAL,
    start_date TIMESTAMP NOT NULL,
    end_date TIMESTAMP,
    timezone VARCHAR DEFAULT 'UTC',
    last_run TIMESTAMP,
    next_run TIMESTAMP,
    enabled BOOLEAN DEFAULT TRUE,
    catchup BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_dag_schedules_next_run ON dag_schedules(next_run);

-- Phase 2: XCom
CREATE TABLE xcom (
    id VARCHAR PRIMARY KEY,
    dag_run_id VARCHAR NOT NULL,
    task_id VARCHAR NOT NULL,
    key VARCHAR NOT NULL,
    value BLOB NOT NULL,
    serialization_type VARCHAR DEFAULT 'pickle',
    created_at TIMESTAMP NOT NULL,
    UNIQUE(dag_run_id, task_id, key)
);

CREATE INDEX idx_xcom_dag_run ON xcom(dag_run_id);
CREATE INDEX idx_xcom_task ON xcom(dag_run_id, task_id);

-- Phase 7: Pools
CREATE TABLE pools (
    name VARCHAR PRIMARY KEY,
    slots INTEGER NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Phase 8: Logging
CREATE TABLE job_logs (
    id VARCHAR PRIMARY KEY,
    job_id VARCHAR NOT NULL,
    dag_run_id VARCHAR,
    node_name VARCHAR,
    logs TEXT,
    created_at TIMESTAMP NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE INDEX idx_job_logs_job ON job_logs(job_id);
CREATE INDEX idx_job_logs_dag_run ON job_logs(dag_run_id, node_name);

-- Phase 10: SLA Monitoring
CREATE TABLE sla_misses (
    id VARCHAR PRIMARY KEY,
    job_id VARCHAR NOT NULL,
    dag_run_id VARCHAR,
    task_id VARCHAR NOT NULL,
    dag_name VARCHAR NOT NULL,
    sla_seconds INTEGER NOT NULL,
    detected_at TIMESTAMP NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE INDEX idx_sla_misses_dag ON sla_misses(dag_run_id);

-- Statistics views
CREATE OR REPLACE VIEW dag_run_stats AS
SELECT 
    dr.id as dag_run_id,
    dr.name as dag_name,
    dr.status as dag_status,
    dr.created_at,
    dr.completed_at,
    COUNT(j.id) as total_jobs,
    SUM(CASE WHEN j.status = 'done' THEN 1 ELSE 0 END) as completed_jobs,
    SUM(CASE WHEN j.status = 'failed' THEN 1 ELSE 0 END) as failed_jobs,
    SUM(CASE WHEN j.status = 'pending' THEN 1 ELSE 0 END) as pending_jobs,
    SUM(CASE WHEN j.status = 'claimed' THEN 1 ELSE 0 END) as running_jobs,
    SUM(CASE WHEN j.status = 'skipped' THEN 1 ELSE 0 END) as skipped_jobs
FROM dag_runs dr
LEFT JOIN jobs j ON dr.id = j.dag_run_id
GROUP BY dr.id, dr.name, dr.status, dr.created_at, dr.completed_at;

CREATE OR REPLACE VIEW dead_letter_queue AS
SELECT * FROM jobs 
WHERE status = 'failed' AND attempts >= max_attempts;
```

---

## 🎓 Complete Example: Production-Ready DAG

```python
"""
production_etl.py - Complete example using all Airflow-like features
"""
from queuack import DuckQueue, Schedule, TriggerRule, TaskGroup, RetryPolicy
from queuack.sensors import FileSensor, TimeSensor
from queuack.alerts import EmailAlert, SlackAlert
from datetime import datetime, timedelta
import logging

# Initialize queue
queue = DuckQueue("production.db")

# Configure alerts
queue.configure_alerts(
    email=EmailAlert(
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        from_addr="alerts@company.com",
        to_addrs=["data-team@company.com"]
    ),
    slack=SlackAlert(
        webhook_url="https://hooks.slack.com/services/XXX"
    )
)

# Configure pools
queue.create_pool('database', slots=5, description='Database connections')
queue.create_pool('api', slots=10, description='API rate limit')

# Define callbacks
def on_failure(context):
    """Send alerts on failure."""
    queue.alerts.email.send_failure(context)
    queue.alerts.slack.send_failure(context)

def on_sla_miss(dag_name, task_id, **kwargs):
    """Alert on SLA miss."""
    queue.alerts.email.send_sla_miss(dag_name, task_id)
    queue.alerts.slack.send_sla_miss(dag_name, task_id)

# Define retry policy
aggressive_retry = RetryPolicy(
    max_attempts=5,
    initial_delay=60,
    max_delay=3600,
    backoff_factor=2.0
)

# Schedule DAG
@queue.scheduled_dag(
    name="daily_etl",
    schedule=Schedule.daily(hour=2, minute=0),
    start_date="2024-01-01",
    catchup=False
)
def daily_etl():
    """Production ETL pipeline with all features."""
    
    with queue.dag(
        "daily_etl",
        description="Daily ETL with full monitoring",
        sla_miss_callback=on_sla_miss
    ) as dag:
        
        # Wait for upstream data
        wait_file = FileSensor(
            name="wait_source_file",
            filepath="/data/daily_extract.csv",
            timeout=3600,
            poke_interval=60
        )
        sensor_task = dag.sensor(wait_file)
        
        # Extract group
        with TaskGroup("extract", dag=dag) as extract_group:
            db_extract = dag.task(
                extract_from_database,
                name="database",
                pool='database',
                retry_policy=aggressive_retry,
                on_failure_callback=on_failure,
                sla=timedelta(minutes=10)
            )
            
            api_extract = dag.task(
                extract_from_api,
                name="api",
                pool='api',
                retry_policy=aggressive_retry,
                on_failure_callback=on_failure
            )
            
            file_extract = dag.task(
                extract_from_file,
                name="file",
                on_failure_callback=on_failure
            )
        
        # Transform group
        with TaskGroup("transform", dag=dag) as transform_group:
            validate = dag.task(
                validate_data,
                name="validate",
                on_failure_callback=on_failure
            )
            
            clean = dag.task(
                clean_data,
                name="clean",
                on_failure_callback=on_failure
            )
            
            enrich = dag.task(
                enrich_data,
                name="enrich",
                pool='database',
                on_failure_callback=on_failure
            )
            
            validate >> clean >> enrich
        
        # Load - runs even if some extracts failed
        load = dag.task(
            load_to_warehouse,
            name="load",
            pool='database',
            trigger_rule=TriggerRule.ONE_SUCCESS,  # Need at least one extract
            retry_policy=aggressive_retry,
            on_failure_callback=on_failure,
            sla=timedelta(minutes=15)
        )
        
        # Notify success
        notify = dag.task(
            send_success_notification,
            name="notify",
            on_failure_callback=on_failure
        )
        
        # Build dependency chain
        sensor_task >> extract_group >> transform_group >> load >> notify
    
    return dag


# Task implementations with context usage
def extract_from_database(**context):
    """Extract with full context."""
    logger = context['task_instance'].get_logger()
    logger.info("Starting database extraction")
    
    # Your extraction logic
    data = {"records": 1000}
    
    # Push to XCom for downstream tasks
    context['task_instance'].xcom_push(key='record_count', value=1000)
    
    logger.info(f"Extracted {data['records']} records")
    return data


def validate_data(**context):
    """Validate with XCom pull."""
    logger = context['task_instance'].get_logger()
    
    # Pull data from multiple extract tasks
    db_count = context['task_instance'].xcom_pull(
        task_ids='extract.database',
        key='record_count'
    )
    
    logger.info(f"Validating {db_count} records from database")
    
    # Validation logic
    if db_count < 100:
        raise ValueError("Insufficient records extracted")
    
    return {"validated": True}


def send_success_notification(**context):
    """Send success notification."""
    execution_date = context['execution_date']
    print(f"✅ ETL completed successfully for {execution_date}")


# Start scheduler and workers
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "scheduler":
        print("Starting scheduler...")
        queue.start_scheduler()
        
        # Keep running
        import signal
        signal.pause()
    
    elif len(sys.argv) > 1 and sys.argv[1] == "worker":
        print("Starting worker...")
        from queuack import Worker
        
        worker = Worker(queue, concurrency=4)
        worker.run()
    
    else:
        print("Usage: python production_etl.py [scheduler|worker]")
```

---

## 🔧 Configuration Management

### queuack.yaml (Configuration File)

```yaml
# queuack.yaml - Global configuration

database:
  path: "queue.db"
  # For production, use persistent storage
  # path: "/var/queuack/production.db"

scheduler:
  enabled: true
  check_interval: 30  # seconds
  max_catchup_runs: 5

workers:
  default_concurrency: 4
  claim_timeout: 300
  max_jobs_in_flight: 8

pools:
  database:
    slots: 5
    description: "Database connection pool"
  api:
    slots: 10
    description: "API rate limiting"
  gpu:
    slots: 2
    description: "GPU resources"

alerts:
  email:
    enabled: true
    smtp_host: "smtp.gmail.com"
    smtp_port: 587
    from: "alerts@company.com"
    to:
      - "team@company.com"
      - "oncall@company.com"
  
  slack:
    enabled: true
    webhook_url: "${SLACK_WEBHOOK_URL}"  # Environment variable

logging:
  level: INFO
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  file: "/var/log/queuack/queuack.log"
  max_bytes: 10485760  # 10MB
  backup_count: 5

monitoring:
  sla_enabled: true
  sla_check_interval: 60  # seconds
  metrics_enabled: true
  metrics_port: 9090  # Prometheus metrics

retention:
  completed_jobs_days: 7
  failed_jobs_days: 30
  logs_days: 14
  xcom_days: 7
```

**Load configuration:**

```python
# queuack/config.py
import yaml
from pathlib import Path
from typing import Any, Dict
import os

class Config:
    """Configuration manager."""
    
    def __init__(self, config_path: str = "queuack.yaml"):
        self.config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self._load_config()
    
    def _load_config(self):
        """Load configuration from YAML file."""
        if not self.config_path.exists():
            # Use defaults
            self._config = self._get_defaults()
            return
        
        with open(self.config_path) as f:
            self._config = yaml.safe_load(f)
        
        # Substitute environment variables
        self._substitute_env_vars(self._config)
    
    def _substitute_env_vars(self, config: dict):
        """Replace ${VAR} with environment variables."""
        for key, value in config.items():
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                env_var = value[2:-1]
                config[key] = os.getenv(env_var, value)
            elif isinstance(value, dict):
                self._substitute_env_vars(value)
    
    def _get_defaults(self) -> dict:
        """Default configuration."""
        return {
            'database': {'path': 'queue.db'},
            'scheduler': {'enabled': True, 'check_interval': 30},
            'workers': {'default_concurrency': 4, 'claim_timeout': 300},
            'pools': {},
            'alerts': {'email': {'enabled': False}, 'slack': {'enabled': False}},
            'logging': {'level': 'INFO'},
            'monitoring': {'sla_enabled': True, 'metrics_enabled': False},
            'retention': {
                'completed_jobs_days': 7,
                'failed_jobs_days': 30,
                'logs_days': 14,
                'xcom_days': 7
            }
        }
    
    def get(self, path: str, default=None) -> Any:
        """Get config value by dot-notation path."""
        keys = path.split('.')
        value = self._config
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value


# Modified DuckQueue initialization
class DuckQueue:
    def __init__(
        self,
        db_path: str = None,
        config_path: str = "queuack.yaml",
        **kwargs
    ):
        # Load configuration
        self.config = Config(config_path)
        
        # Override with explicit parameters
        if db_path is None:
            db_path = self.config.get('database.path', 'queue.db')
        
        self.db_path = db_path
        
        # Initialize with config defaults
        self.default_queue = kwargs.get('default_queue', 'default')
        self._workers_num = kwargs.get('workers_num')
        self._worker_concurrency = kwargs.get(
            'worker_concurrency',
            self.config.get('workers.default_concurrency', 4)
        )
        
        # ... rest of initialization
```

---

## 📊 Metrics & Observability (Bonus: Prometheus Integration)

```python
# queuack/metrics.py
from prometheus_client import Counter, Gauge, Histogram, start_http_server
import threading

class MetricsCollector:
    """Prometheus metrics collector."""
    
    def __init__(self, queue: DuckQueue, port: int = 9090):
        self.queue = queue
        self.port = port
        
        # Define metrics
        self.jobs_enqueued = Counter(
            'queuack_jobs_enqueued_total',
            'Total jobs enqueued',
            ['queue', 'dag']
        )
        
        self.jobs_completed = Counter(
            'queuack_jobs_completed_total',
            'Total jobs completed',
            ['queue', 'dag', 'status']
        )
        
        self.jobs_pending = Gauge(
            'queuack_jobs_pending',
            'Current pending jobs',
            ['queue']
        )
        
        self.jobs_claimed = Gauge(
            'queuack_jobs_claimed',
            'Current claimed jobs',
            ['queue']
        )
        
        self.job_duration = Histogram(
            'queuack_job_duration_seconds',
            'Job execution duration',
            ['queue', 'dag', 'task']
        )
        
        self.dag_runs_active = Gauge(
            'queuack_dag_runs_active',
            'Active DAG runs',
            ['dag']
        )
        
        self.sla_misses = Counter(
            'queuack_sla_misses_total',
            'Total SLA misses',
            ['dag', 'task']
        )
        
        self._running = False
        self._thread = None
    
    def start(self):
        """Start metrics HTTP server."""
        start_http_server(self.port)
        
        self._running = True
        self._thread = threading.Thread(target=self._collect_loop, daemon=True)
        self._thread.start()
        
        logger.info(f"Metrics server started on port {self.port}")
    
    def stop(self):
        """Stop metrics collection."""
        self._running = False
        if self._thread:
            self._thread.join()
    
    def _collect_loop(self):
        """Periodically update gauge metrics."""
        import time
        
        while self._running:
            try:
                # Update pending/claimed counts
                stats = self.queue.stats()
                
                self.jobs_pending.labels(queue=self.queue.default_queue).set(
                    stats.get('pending', 0)
                )
                self.jobs_claimed.labels(queue=self.queue.default_queue).set(
                    stats.get('claimed', 0)
                )
                
                # Update active DAG runs
                with self.queue._db_lock:
                    results = self.queue.conn.execute("""
                        SELECT name, COUNT(*) FROM dag_runs
                        WHERE status = 'running'
                        GROUP BY name
                    """).fetchall()
                    
                    for dag_name, count in results:
                        self.dag_runs_active.labels(dag=dag_name).set(count)
            
            except Exception as e:
                logger.error(f"Metrics collection error: {e}")
            
            time.sleep(15)  # Update every 15 seconds
    
    def record_job_enqueue(self, queue: str, dag: str = None):
        """Record job enqueued."""
        self.jobs_enqueued.labels(queue=queue, dag=dag or 'none').inc()
    
    def record_job_complete(self, queue: str, dag: str, status: str):
        """Record job completion."""
        self.jobs_completed.labels(queue=queue, dag=dag, status=status).inc()
    
    def record_job_duration(self, queue: str, dag: str, task: str, duration: float):
        """Record job execution time."""
        self.job_duration.labels(queue=queue, dag=dag, task=task).observe(duration)
    
    def record_sla_miss(self, dag: str, task: str):
        """Record SLA miss."""
        self.sla_misses.labels(dag=dag, task=task).inc()


# Add to DuckQueue
class DuckQueue:
    def __init__(self, *args, **kwargs):
        # ... existing init
        
        # Initialize metrics if enabled
        if self.config.get('monitoring.metrics_enabled', False):
            self.metrics = MetricsCollector(
                self,
                port=self.config.get('monitoring.metrics_port', 9090)
            )
            self.metrics.start()
        else:
            self.metrics = None
```

---

## 🧹 Data Retention & Cleanup

```python
# queuack/retention.py
from datetime import datetime, timedelta

class RetentionManager:
    """Manages data retention and cleanup."""
    
    def __init__(self, queue: DuckQueue):
        self.queue = queue
        self.config = queue.config
        self._running = False
        self._thread = None
    
    def start(self):
        """Start retention manager."""
        self._running = True
        self._thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._thread.start()
    
    def stop(self):
        """Stop retention manager."""
        self._running = False
        if self._thread:
            self._thread.join()
    
    def _cleanup_loop(self):
        """Periodic cleanup job."""
        import time
        
        while self._running:
            try:
                self.cleanup_all()
            except Exception as e:
                logger.error(f"Retention cleanup error: {e}")
            
            # Run daily
            time.sleep(86400)
    
    def cleanup_all(self):
        """Run all cleanup tasks."""
        self.cleanup_completed_jobs()
        self.cleanup_old_logs()
        self.cleanup_old_xcom()
        self.cleanup_old_dag_runs()
    
    def cleanup_completed_jobs(self):
        """Delete old completed jobs."""
        days = self.config.get('retention.completed_jobs_days', 7)
        cutoff = datetime.now() - timedelta(days=days)
        
        with self.queue._db_lock:
            result = self.queue.conn.execute("""
                DELETE FROM jobs
                WHERE status = 'done'
                AND completed_at < ?
                RETURNING COUNT(*)
            """, [cutoff]).fetchone()
            
            count = result[0] if result else 0
            logger.info(f"Cleaned up {count} completed jobs older than {days} days")
    
    def cleanup_old_logs(self):
        """Delete old job logs."""
        days = self.config.get('retention.logs_days', 14)
        cutoff = datetime.now() - timedelta(days=days)
        
        with self.queue._db_lock:
            result = self.queue.conn.execute("""
                DELETE FROM job_logs
                WHERE created_at < ?
                RETURNING COUNT(*)
            """, [cutoff]).fetchone()
            
            count = result[0] if result else 0
            logger.info(f"Cleaned up {count} log entries older than {days} days")
    
    def cleanup_old_xcom(self):
        """Delete old XCom data."""
        days = self.config.get('retention.xcom_days', 7)
        cutoff = datetime.now() - timedelta(days=days)
        
        with self.queue._db_lock:
            result = self.queue.conn.execute("""
                DELETE FROM xcom
                WHERE created_at < ?
                RETURNING COUNT(*)
            """, [cutoff]).fetchone()
            
            count = result[0] if result else 0
            logger.info(f"Cleaned up {count} XCom entries older than {days} days")
    
    def cleanup_old_dag_runs(self):
        """Delete old completed DAG runs."""
        days = self.config.get('retention.completed_jobs_days', 7)
        cutoff = datetime.now() - timedelta(days=days)
        
        with self.queue._db_lock:
            # First delete associated jobs
            self.queue.conn.execute("""
                DELETE FROM jobs
                WHERE dag_run_id IN (
                    SELECT id FROM dag_runs
                    WHERE status IN ('done', 'failed')
                    AND completed_at < ?
                )
            """, [cutoff])
            
            # Then delete DAG runs
            result = self.queue.conn.execute("""
                DELETE FROM dag_runs
                WHERE status IN ('done', 'failed')
                AND completed_at < ?
                RETURNING COUNT(*)
            """, [cutoff]).fetchone()
            
            count = result[0] if result else 0
            logger.info(f"Cleaned up {count} DAG runs older than {days} days")
```

---

## 🐳 Docker Deployment

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY queuack/ ./queuack/
COPY dags/ ./dags/

# Create data directory
RUN mkdir -p /data

# Expose metrics port
EXPOSE 9090

# Default command (can be overridden)
CMD ["python", "-m", "queuack.cli", "scheduler", "start"]
```

### docker-compose.yml

```yaml
version: '3.8'

services:
  scheduler:
    build: .
    command: python -m queuack.cli scheduler start
    volumes:
      - ./data:/data
      - ./dags:/app/dags
      - ./queuack.yaml:/app/queuack.yaml
    environment:
      - QUEUACK_DB=/data/queue.db
      - SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL}
    restart: unless-stopped
    networks:
      - queuack

  worker:
    build: .
    command: python -m queuack.cli workers start --concurrency 4
    volumes:
      - ./data:/data
      - ./dags:/app/dags
      - ./queuack.yaml:/app/queuack.yaml
    environment:
      - QUEUACK_DB=/data/queue.db
    restart: unless-stopped
    deploy:
      replicas: 3  # Run 3 worker instances
    networks:
      - queuack
    depends_on:
      - scheduler

  metrics:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus-data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
    networks:
      - queuack

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    volumes:
      - grafana-data:/var/lib/grafana
      - ./grafana-dashboards:/etc/grafana/provisioning/dashboards
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    networks:
      - queuack
    depends_on:
      - metrics

volumes:
  prometheus-data:
  grafana-data:

networks:
  queuack:
    driver: bridge
```

### prometheus.yml

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'queuack'
    static_configs:
      - targets:
        - 'scheduler:9090'
        - 'worker:9090'
```

---

## 🚀 Quick Start Guide (After All Phases)

### 1. Installation

```bash
pip install queuack[all]  # Includes all optional dependencies
```

### 2. Initialize Configuration

```bash
queuack init  # Creates queuack.yaml with defaults
```

### 3. Create Your First DAG

```python
# dags/hello_world.py
from queuack import DuckQueue, Schedule

queue = DuckQueue()

@queue.scheduled_dag(
    name="hello_world",
    schedule=Schedule.daily(hour=9)
)
def hello_world_dag():
    with queue.dag("hello_world") as dag:
        hello = dag.task(
            lambda: print("Hello, World!"),
            name="hello"
        )
    return dag
```

### 4. Start Services

```bash
# Terminal 1: Start scheduler
queuack scheduler start

# Terminal 2: Start worker
queuack workers start --concurrency 4

# Or use Docker Compose
docker-compose up -d
```

### 5. Monitor

```bash
# View DAGs
queuack dags list

# Trigger manually
queuack dags trigger hello_world

# Check status
queuack dags show hello_world

# View metrics
open http://localhost:9090  # Prometheus
open http://localhost:3000  # Grafana
```

---

## 📈 Performance Benchmarks (Expected)

| Metric | Current | After Phase 10 | Airflow Equivalent |
|--------|---------|----------------|-------------------|
| Enqueue throughput | 5,000/s | 5,000/s | 1,000/s |
| Claim throughput | 2,000/s | 1,800/s | 500/s |
| Scheduler latency | N/A | <5s | ~30s |
| Memory footprint | 50MB | 150MB | 500MB+ |
| Cold start time | <1s | <2s | ~30s |
| DAG parse time (100 tasks) | N/A | <100ms | ~1s |
| Database file size (1M jobs) | ~500MB | ~800MB | 10GB+ |

---

## 🎯 Final Recommendations

### **Minimum Viable Airflow (Phases 1-3)**
**Time:** 4 weeks | **Effort:** Medium | **Value:** 🔴 Critical

Delivers:
- Scheduled DAGs
- Inter-task communication (XCom)
- Operational CLI
- **80% of Airflow developer experience**

### **Full Feature Parity (Phases 1-6)**
**Time:** 7 weeks | **Effort:** High | **Value:** 🟡 High

Adds:
- Dependency operators (`>>`)
- Advanced retry logic
- Sensors
- **95% of Airflow functionality**

### **Production Ready (All Phases)**
**Time:** 12 weeks | **Effort:** Very High | **Value:** 🟢 Complete

Adds:
- Resource pools
- SLA monitoring
- Complete observability
- **100% production-ready orchestration**

---

## 🎓 Migration Strategy

### For New Users
Start fresh with full feature set. Examples and documentation guide the way.

### For Existing Queuack Users
1. **Phase 0** (Week 0): Deprecation warnings for old patterns
2. **Phase 1-3** (Weeks 1-4): Soft launch with opt-in features
3. **Phase 4-6** (Weeks 5-7): Promote new patterns in docs
4. **Phase 7-10** (Weeks 8-12): Full feature rollout
5. **Phase 11** (Week 13+): Deprecate old APIs (with migration tool)

### For Airflow Users
**Direct Translation Guide:**

```python
# Airflow
from airflow import DAG
from airflow.operators.python import PythonOperator

with DAG('my_dag', schedule='@daily') as dag:
    task1 = PythonOperator(task_id='task1', python_callable=func1)
    task2 = PythonOperator(task_id='task2', python_callable=func2)
    task1 >> task2

# Queuack (After Phase 10)
from queuack import DuckQueue, Schedule

queue = DuckQueue()

@queue.scheduled_dag('my_dag', schedule=Schedule.daily())
def my_dag():
    with queue.dag('my_dag') as dag:
        task1 = dag.task(func1, name='task1')
        task2 = dag.task(func2, name='task2')
        task1 >> task2
    return dag
```

**95% compatible syntax, 100% simpler infrastructure!**

---

## 📚 Documentation Structure (To Build)

```
docs/
├── getting-started/
│   ├── installation.md
│   ├── quickstart.md
│   └── core-concepts.md
├── user-guide/
│   ├── scheduling.md
│   ├── dags.md
│   ├── tasks.md
│   ├── dependencies.md
│   ├── xcom.md
│   ├── sensors.md
│   ├── pools.md
│   └── callbacks.md
├── operators-reference/
│   ├── python.md
│   ├── bash.md
│   └── sensors.md
├── cli-reference/
│   ├── dags.md
│   ├── tasks.md
│   ├── workers.md
│   └── scheduler.md
├── deployment/
│   ├── docker.md
│   ├── kubernetes.md
│   └── production-best-practices.md
├── monitoring/
│   ├── metrics.md
│   ├── logging.md
│   └── alerting.md
└── migration/
    ├── from-celery.md
    ├── from-airflow.md
    └── api-changelog.md
```

---

## ✅ Success Criteria

**Phase 1-3 Complete When:**
- ✅ DAGs can be scheduled with cron expressions
- ✅ Tasks can pass data via XCom
- ✅ CLI can trigger/monitor DAGs
- ✅ Documentation covers 80% of use cases
- ✅ Migration path from current version clear

**Phase 4-10 Complete When:**
- ✅ All Airflow concepts have Queuack equivalents
- ✅ Production deployments run stably for 30 days
- ✅ Performance meets or exceeds benchmarks
- ✅ Community provides positive feedback
- ✅ Zero critical bugs in issue tracker

---

**This roadmap transforms Queuack from a job queue into a production-ready workflow orchestration platform while preserving its core philosophy: simplicity, single-file database, and zero external dependencies (except optional features).**# Queuack → Airflow Parity Assessment & Implementation Roadmap

**Goal:** Transform Queuack from a basic job queue into an Airflow-like workflow orchestration system while maintaining its lightweight, single-file database philosophy.

---

## 📊 Feature Comparison Matrix

| Feature | Airflow | Queuack Current | Gap Severity | Implementation Effort |
|---------|---------|-----------------|--------------|----------------------|
| **Core Scheduling** |
| Cron/Interval Scheduling | ✅ `@daily`, `@hourly` | ❌ Manual enqueue only | 🔴 Critical | Medium |
| Start/End Dates | ✅ Full support | ❌ None | 🟡 High | Low |
| Catchup/Backfill | ✅ Automatic | ❌ None | 🟡 High | High |
| Timezone Support | ✅ Per-DAG | ❌ None | 🟢 Medium | Low |
| **DAG Definition** |
| Context Manager API | ✅ `with DAG()` | ✅ `with queue.dag()` | ✅ Complete | - |
| Dependency Operators | ✅ `task1 >> task2` | ❌ String refs only | 🟡 High | Low |
| Task Groups | ✅ Nested groups | ❌ Flat only | 🟢 Medium | Medium |
| Dynamic Task Generation | ✅ `.expand()` | ⚠️ Manual loops | 🟡 High | Medium |
| **Execution & State** |
| Rich Task States | ✅ 10+ states | ⚠️ 6 states | 🟡 High | Low |
| Task Instance Tracking | ✅ Per run | ✅ Via `dag_run_id` | ✅ Complete | - |
| XCom (Data Passing) | ✅ Built-in | ❌ None | 🔴 Critical | Medium |
| Execution Context | ✅ Rich context | ❌ No context | 🔴 Critical | Medium |
| **Retry & Recovery** |
| Exponential Backoff | ✅ Configurable | ❌ Fixed retries | 🟡 High | Low |
| Retry Delay | ✅ Per-task | ❌ Immediate | 🟡 High | Low |
| Task Timeout | ✅ Per-task | ✅ Per-task | ✅ Complete | - |
| **Triggers & Sensors** |
| Trigger Rules | ✅ 8+ rules | ⚠️ ALL/ANY only | 🟡 High | Low |
| Sensors | ✅ Many types | ❌ None | 🟡 High | High |
| External Triggers | ✅ API/CLI | ❌ None | 🔴 Critical | Medium |
| **Observability** |
| CLI Management | ✅ Comprehensive | ⚠️ Basic stats | 🔴 Critical | Medium |
| Task Logs | ✅ Per-task storage | ❌ None | 🟡 High | Medium |
| DAG Visualization | ✅ Web UI | ⚠️ Mermaid only | 🟢 Medium | - |
| Metrics/Monitoring | ✅ Rich metrics | ⚠️ Basic stats | 🟢 Medium | Medium |
| **Resource Management** |
| Pools/Slots | ✅ Per-resource | ❌ None | 🟡 High | High |
| Priority Weights | ✅ Per-task | ✅ Per-task | ✅ Complete | - |
| Concurrency Limits | ✅ DAG-level | ⚠️ Worker-level | 🟢 Medium | Medium |
| **Alerting & Callbacks** |
| Email Alerts | ✅ Built-in | ❌ None | 🟡 High | Medium |
| Custom Callbacks | ✅ 5+ hooks | ❌ None | 🟡 High | Low |
| SLA Monitoring | ✅ Per-task | ❌ None | 🟢 Medium | Medium |

**Legend:**
- 🔴 Critical: Blocks Airflow-like experience
- 🟡 High: Significantly impacts usability
- 🟢 Medium: Nice-to-have for feature parity

---

## 🎯 Phase 1: Core Scheduling (Weeks 1-2)

### 1.1 Schedule Specification

**Current State:**
```python
# Manual enqueue only
with queue.dag("etl") as dag:
    extract = dag.enqueue(extract_data, name="extract")
```

**Target State:**
```python
from queuack import DuckQueue, Schedule

queue = DuckQueue("queue.db")

# Declarative scheduling
@queue.scheduled_dag(
    name="daily_etl",
    schedule=Schedule.daily(hour=2, minute=30),  # 02:30 UTC
    start_date="2024-01-01",
    catchup=False
)
def daily_etl():
    with queue.dag("daily_etl") as dag:
        extract = dag.enqueue(extract_data, name="extract")
        transform = dag.enqueue(transform_data, name="transform", depends_on="extract")
    return dag
```

**Implementation Plan:**

```python
# queuack/schedule.py
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Callable
import croniter

@dataclass
class Schedule:
    """Schedule specification for DAG runs."""
    
    # Cron expression or interval
    schedule_type: str  # 'cron', 'interval', 'once'
    cron_expression: Optional[str] = None
    interval: Optional[timedelta] = None
    
    start_date: datetime = None
    end_date: Optional[datetime] = None
    timezone: str = "UTC"
    
    @classmethod
    def cron(cls, expression: str, **kwargs):
        """Schedule using cron expression."""
        return cls(schedule_type='cron', cron_expression=expression, **kwargs)
    
    @classmethod
    def daily(cls, hour: int = 0, minute: int = 0, **kwargs):
        """Daily at specific time."""
        return cls.cron(f"{minute} {hour} * * *", **kwargs)
    
    @classmethod
    def hourly(cls, minute: int = 0, **kwargs):
        """Every hour."""
        return cls.cron(f"{minute} * * * *", **kwargs)
    
    @classmethod
    def interval(cls, days=0, hours=0, minutes=0, **kwargs):
        """Fixed interval."""
        return cls(
            schedule_type='interval',
            interval=timedelta(days=days, hours=hours, minutes=minutes),
            **kwargs
        )
    
    def get_next_run(self, after: datetime) -> Optional[datetime]:
        """Calculate next run time after given datetime."""
        if self.end_date and after >= self.end_date:
            return None
        
        if self.schedule_type == 'cron':
            cron = croniter.croniter(self.cron_expression, after)
            next_run = cron.get_next(datetime)
            return next_run if not self.end_date or next_run <= self.end_date else None
        
        elif self.schedule_type == 'interval':
            next_run = after + self.interval
            return next_run if not self.end_date or next_run <= self.end_date else None
        
        return None


# queuack/scheduler.py
class DAGScheduler:
    """Background scheduler that triggers DAGs based on schedules."""
    
    def __init__(self, queue: DuckQueue):
        self.queue = queue
        self.scheduled_dags: Dict[str, Tuple[Callable, Schedule]] = {}
        self._running = False
        self._thread = None
    
    def register_dag(self, name: str, dag_factory: Callable, schedule: Schedule):
        """Register a DAG with its schedule."""
        self.scheduled_dags[name] = (dag_factory, schedule)
        
        # Persist schedule to database
        with self.queue._db_lock:
            self.queue.conn.execute("""
                INSERT OR REPLACE INTO dag_schedules 
                (name, schedule_type, cron_expression, interval_seconds, 
                 start_date, end_date, timezone, last_run, next_run)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """, [
                name,
                schedule.schedule_type,
                schedule.cron_expression,
                schedule.interval.total_seconds() if schedule.interval else None,
                schedule.start_date,
                schedule.end_date,
                schedule.timezone,
                schedule.get_next_run(datetime.now())
            ])
    
    def start(self):
        """Start scheduler background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self._thread.start()
    
    def stop(self):
        """Stop scheduler."""
        self._running = False
        if self._thread:
            self._thread.join()
    
    def _run_scheduler(self):
        """Main scheduler loop."""
        while self._running:
            now = datetime.now()
            
            with self.queue._db_lock:
                # Find DAGs that need to run
                results = self.queue.conn.execute("""
                    SELECT name, next_run FROM dag_schedules
                    WHERE next_run <= ? AND (end_date IS NULL OR end_date > ?)
                """, [now, now]).fetchall()
                
                for name, next_run_str in results:
                    if name not in self.scheduled_dags:
                        continue
                    
                    # Trigger DAG
                    dag_factory, schedule = self.scheduled_dags[name]
                    self._trigger_dag(name, dag_factory, schedule)
                    
                    # Update next run
                    next_run = schedule.get_next_run(datetime.fromisoformat(next_run_str))
                    self.queue.conn.execute("""
                        UPDATE dag_schedules
                        SET last_run = ?, next_run = ?
                        WHERE name = ?
                    """, [now, next_run, name])
            
            time.sleep(30)  # Check every 30 seconds
    
    def _trigger_dag(self, name: str, dag_factory: Callable, schedule: Schedule):
        """Execute DAG factory to create and submit DAG."""
        try:
            dag = dag_factory()
            dag.submit()
            logger.info(f"Scheduled DAG '{name}' triggered successfully")
        except Exception as e:
            logger.error(f"Failed to trigger DAG '{name}': {e}")


# Add to DuckQueue
class DuckQueue:
    def __init__(self, *args, **kwargs):
        # ... existing init
        self._scheduler = DAGScheduler(self)
    
    def scheduled_dag(self, name: str, schedule: Schedule, start_date: str = None, 
                     catchup: bool = False):
        """Decorator for scheduled DAGs."""
        if start_date:
            schedule.start_date = datetime.fromisoformat(start_date)
        
        def decorator(dag_factory: Callable):
            self._scheduler.register_dag(name, dag_factory, schedule)
            return dag_factory
        
        return decorator
    
    def start_scheduler(self):
        """Start background scheduler."""
        self._scheduler.start()
```

**Database Schema Changes:**
```sql
CREATE TABLE dag_schedules (
    name VARCHAR PRIMARY KEY,
    schedule_type VARCHAR NOT NULL,
    cron_expression VARCHAR,
    interval_seconds REAL,
    start_date TIMESTAMP NOT NULL,
    end_date TIMESTAMP,
    timezone VARCHAR DEFAULT 'UTC',
    last_run TIMESTAMP,
    next_run TIMESTAMP,
    enabled BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_dag_schedules_next_run ON dag_schedules(next_run);
```

**Effort:** Medium (3-4 days)
**Dependencies:** `croniter` library

---

## 🎯 Phase 2: XCom & Execution Context (Weeks 2-3)

### 2.1 XCom (Cross-Communication)

**Current State:**
```python
# No way to pass data between tasks
def extract():
    return {"users": [1, 2, 3]}  # Lost!

def transform():
    users = ???  # Can't access extract's result
```

**Target State:**
```python
def extract(**context):
    data = {"users": [1, 2, 3]}
    context['task_instance'].xcom_push(key='users', value=data)
    return data  # Also auto-pushed as return value

def transform(**context):
    users = context['task_instance'].xcom_pull(task_ids='extract', key='return_value')
    # Or explicit key
    users = context['task_instance'].xcom_pull(task_ids='extract', key='users')
    return process(users)
```

**Implementation Plan:**

```python
# queuack/xcom.py
import pickle
import json
from typing import Any, Optional

class XComManager:
    """Manages inter-task communication."""
    
    def __init__(self, queue: DuckQueue):
        self.queue = queue
    
    def push(self, dag_run_id: str, task_id: str, key: str, value: Any) -> str:
        """Store value in XCom."""
        xcom_id = str(uuid.uuid4())
        
        # Serialize value
        try:
            serialized = json.dumps(value)
            serialization_type = 'json'
        except (TypeError, ValueError):
            serialized = pickle.dumps(value)
            serialization_type = 'pickle'
        
        with self.queue._db_lock:
            self.queue.conn.execute("""
                INSERT INTO xcom (id, dag_run_id, task_id, key, value, 
                                 serialization_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, [
                xcom_id, dag_run_id, task_id, key, 
                serialized, serialization_type, datetime.now()
            ])
        
        return xcom_id
    
    def pull(self, dag_run_id: str, task_ids: Union[str, List[str]], 
             key: str = 'return_value') -> Any:
        """Retrieve value from XCom."""
        if isinstance(task_ids, str):
            task_ids = [task_ids]
        
        with self.queue._db_lock:
            placeholders = ','.join(['?' for _ in task_ids])
            result = self.queue.conn.execute(f"""
                SELECT value, serialization_type FROM xcom
                WHERE dag_run_id = ? AND task_id IN ({placeholders}) AND key = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, [dag_run_id] + task_ids + [key]).fetchone()
        
        if not result:
            return None
        
        value, serialization_type = result
        
        if serialization_type == 'json':
            return json.loads(value)
        else:
            return pickle.loads(value)
    
    def clear(self, dag_run_id: str, task_id: Optional[str] = None):
        """Clear XCom values."""
        with self.queue._db_lock:
            if task_id:
                self.queue.conn.execute(
                    "DELETE FROM xcom WHERE dag_run_id = ? AND task_id = ?",
                    [dag_run_id, task_id]
                )
            else:
                self.queue.conn.execute(
                    "DELETE FROM xcom WHERE dag_run_id = ?",
                    [dag_run_id]
                )


# queuack/context.py
@dataclass
class TaskInstance:
    """Execution context for a single task."""
    job_id: str
    dag_run_id: str
    task_id: str
    execution_date: datetime
    xcom_manager: XComManager
    
    def xcom_push(self, key: str, value: Any) -> str:
        """Push value to XCom."""
        return self.xcom_manager.push(self.dag_run_id, self.task_id, key, value)
    
    def xcom_pull(self, task_ids: Union[str, List[str]], 
                  key: str = 'return_value') -> Any:
        """Pull value from XCom."""
        return self.xcom_manager.pull(self.dag_run_id, task_ids, key)


@dataclass
class ExecutionContext:
    """Full execution context passed to tasks."""
    task_instance: TaskInstance
    dag_run_id: str
    execution_date: datetime
    dag_name: str
    task_id: str
    attempt: int
    
    # Convenience shortcuts
    @property
    def ti(self):
        return self.task_instance
    
    def to_dict(self):
        """Convert to dict for **context unpacking."""
        return {
            'task_instance': self.task_instance,
            'ti': self.task_instance,
            'dag_run_id': self.dag_run_id,
            'execution_date': self.execution_date,
            'dag_name': self.dag_name,
            'task_id': self.task_id,
            'attempt': self.attempt
        }


# Modified Job execution
@dataclass
class Job:
    # ... existing fields
    
    def execute(self, context: Optional[ExecutionContext] = None) -> Any:
        """Execute with optional context."""
        func = pickle.loads(self.func)
        args = pickle.loads(self.args)
        kwargs = pickle.loads(self.kwargs)
        
        # Inject context if function accepts **context
        if context:
            import inspect
            sig = inspect.signature(func)
            
            # Check if function has **kwargs or explicit context params
            if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                kwargs.update(context.to_dict())
            elif 'context' in sig.parameters:
                kwargs['context'] = context
        
        result = func(*args, **kwargs)
        
        # Auto-push return value to XCom
        if context and result is not None:
            context.task_instance.xcom_push('return_value', result)
        
        return result
```

**Database Schema Changes:**
```sql
CREATE TABLE xcom (
    id VARCHAR PRIMARY KEY,
    dag_run_id VARCHAR NOT NULL,
    task_id VARCHAR NOT NULL,
    key VARCHAR NOT NULL,
    value BLOB NOT NULL,
    serialization_type VARCHAR DEFAULT 'pickle',
    created_at TIMESTAMP NOT NULL,
    UNIQUE(dag_run_id, task_id, key)
);

CREATE INDEX idx_xcom_dag_run ON xcom(dag_run_id);
CREATE INDEX idx_xcom_task ON xcom(dag_run_id, task_id);
```

**Effort:** Medium (4-5 days)

---

## 🎯 Phase 3: Enhanced CLI & Observability (Week 4)

### 3.1 Comprehensive CLI

**Target Commands:**
```bash
# DAG management
queuack dags list
queuack dags show my_dag
queuack dags trigger my_dag --conf '{"key": "value"}'
queuack dags pause my_dag
queuack dags unpause my_dag
queuack dags delete my_dag

# DAG runs
queuack dags list-runs my_dag
queuack dags run-state my_dag <run_id>
queuack dags backfill my_dag --start 2024-01-01 --end 2024-01-31

# Tasks
queuack tasks list my_dag
queuack tasks state my_dag <run_id> <task_id>
queuack tasks logs my_dag <run_id> <task_id>
queuack tasks clear my_dag <task_id>  # Retry

# Workers
queuack workers list
queuack workers start --concurrency 4
queuack workers stop <worker_id>

# Scheduler
queuack scheduler start
queuack scheduler status
```

**Implementation:**

```python
# queuack/cli.py
import click
from tabulate import tabulate

@click.group()
@click.option('--db', default='queue.db', envvar='QUEUACK_DB')
@click.pass_context
def cli(ctx, db):
    """Queuack - Lightweight workflow orchestration."""
    ctx.ensure_object(dict)
    ctx.obj['queue'] = DuckQueue(db)


@cli.group()
def dags():
    """DAG management commands."""
    pass


@dags.command('list')
@click.pass_context
def list_dags(ctx):
    """List all DAGs."""
    queue = ctx.obj['queue']
    
    with queue._db_lock:
        results = queue.conn.execute("""
            SELECT DISTINCT name, description, 
                   COUNT(*) as runs,
                   MAX(created_at) as last_run
            FROM dag_runs
            GROUP BY name, description
            ORDER BY last_run DESC
        """).fetchall()
    
    table = [[r[0], r[1], r[2], r[3]] for r in results]
    click.echo(tabulate(
        table,
        headers=['DAG', 'Description', 'Runs', 'Last Run'],
        tablefmt='grid'
    ))


@dags.command('trigger')
@click.argument('dag_name')
@click.option('--conf', help='JSON config')
@click.option('--wait', is_flag=True, help='Wait for completion')
@click.pass_context
def trigger_dag(ctx, dag_name, conf, wait):
    """Manually trigger a DAG run."""
    queue = ctx.obj['queue']
    
    # Parse config
    config = {}
    if conf:
        import json
        config = json.loads(conf)
    
    # Find DAG factory and trigger
    if hasattr(queue._scheduler, 'scheduled_dags') and dag_name in queue._scheduler.scheduled_dags:
        dag_factory, _ = queue._scheduler.scheduled_dags[dag_name]
        dag = dag_factory()
        run_id = dag.submit()
        
        click.echo(f"✓ Triggered DAG '{dag_name}' (run_id: {run_id})")
        
        if wait:
            from queuack.dag_context import DAGRun
            dag_run = DAGRun(queue, run_id)
            
            import time
            while not dag_run.is_complete():
                progress = dag_run.get_progress()
                click.echo(f"Progress: {progress}")
                time.sleep(2)
            
            click.echo(f"✓ DAG completed: {dag_run.get_status()}")
    else:
        click.echo(f"❌ DAG '{dag_name}' not found", err=True)


@dags.command('show')
@click.argument('dag_name')
@click.pass_context
def show_dag(ctx, dag_name):
    """Show DAG structure."""
    queue = ctx.obj['queue']
    
    # Get latest DAG run
    with queue._db_lock:
        result = queue.conn.execute("""
            SELECT id FROM dag_runs
            WHERE name = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, [dag_name]).fetchone()
    
    if not result:
        click.echo(f"❌ No runs found for DAG '{dag_name}'", err=True)
        return
    
    dag_run_id = result[0]
    
    # Get tasks
    with queue._db_lock:
        tasks = queue.conn.execute("""
            SELECT node_name, status, dependencies.parent_job_id
            FROM jobs
            LEFT JOIN job_dependencies dependencies ON jobs.id = dependencies.child_job_id
            WHERE dag_run_id = ?
        """, [dag_run_id]).fetchall()
    
    # Build dependency graph
    click.echo(f"\nDAG: {dag_name}")
    click.echo("="*60)
    
    for task_name, status, parent in tasks:
        indent = "  " if parent else ""
        status_icon = {
            'done': '✓',
            'failed': '✗',
            'pending': '○',
            'claimed': '◐',
            'skipped': '⊗'
        }.get(status, '?')
        
        click.echo(f"{indent}{status_icon} {task_name} [{status}]")


@cli.group()
def tasks():
    """Task management commands."""
    pass


@tasks.command('logs')
@click.argument('dag_name')
@click.argument('run_id')
@click.argument('task_id')
@click.pass_context
def task_logs(ctx, dag_name, run_id, task_id):
    """Show task execution logs."""
    queue = ctx.obj['queue']
    
    with queue._db_lock:
        result = queue.conn.execute("""
            SELECT logs FROM job_logs
            WHERE dag_run_id = ? AND node_name = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, [run_id, task_id]).fetchone()
    
    if result:
        click.echo(result[0])
    else:
        click.echo("No logs found")


@cli.group()
def workers():
    """Worker management commands."""
    pass


@workers.command('start')
@click.option('--concurrency', default=4)
@click.pass_context
def start_worker(ctx, concurrency):
    """Start a worker process."""
    queue = ctx.obj['queue']
    from queuack import Worker
    
    click.echo(f"Starting worker (concurrency={concurrency})...")
    worker = Worker(queue, concurrency=concurrency)
    worker.run()


@cli.group()
def scheduler():
    """Scheduler management commands."""
    pass


@scheduler.command('start')
@click.pass_context
def start_scheduler(ctx):
    """Start the scheduler."""
    queue = ctx.obj['queue']
    
    click.echo("Starting scheduler...")
    queue.start_scheduler()
    
    # Keep running
    import signal
    import time
    
    def handler(sig, frame):
        click.echo("\nStopping scheduler...")
        queue._scheduler.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
    
    while True:
        time.sleep(1)


if __name__ == '__main__':
    cli()
```

**Effort:** Medium (3-4 days)

---

## 🎯 Phase 4: Dependency Operators & Syntactic Sugar (Week 5)

### 4.1 `>>` and `<<` Operators

**Target State:**
```python
with queue.dag("pipeline") as dag:
    extract = dag.task(extract_data, name="extract")
    transform = dag.task(transform_data, name="transform")
    load = dag.task(load_data, name="load")
    
    # Airflow-style chaining
    extract >> transform >> load
    
    # Or fan-out
    extract >> [transform1, transform2] >> load
    
    # Or fan-in
    [extract1, extract2] >> merge >> load
```

**Implementation:**

```python
# queuack/task.py
class Task:
    """Wrapper for task that supports >> operator."""
    
    def __init__(self, dag_context: DAGContext, func: Callable, 
                 name: str, **kwargs):
        self.dag = dag_context
        self.func = func
        self.name = name
        self.kwargs = kwargs
        self.job_id = None
        self._dependencies = []
    
    def __rshift__(self, other):
        """Implement >> operator (self >> other)."""
        if isinstance(other, list):
            for task in other:
                task.set_upstream(self)
            return other
        else:
            other.set_upstream(self)
            return other
    
    def __lshift__(self, other):
        """Implement << operator (self << other)."""
        if isinstance(other, list):
            for task in other:
                self.set_upstream(task)
            return self
        else:
            self.set_upstream(other)
            return self
    
    def set_upstream(self, task):
        """Add upstream dependency."""
        if isinstance(task, Task):
            self._dependencies.append(task.name)
        else:
            self._dependencies.append(task)
    
    def set_downstream(self, task):
        """Add downstream dependency (reverse of upstream)."""
        if isinstance(task, Task):
            task.set_upstream(self)
        else:
            task.set_upstream(self.name)
    
    def submit(self):
        """Actually enqueue the task."""
        if not self.job_id:
            self.job_id = self.dag.enqueue(
                self.func,
                name=self.name,
                depends_on=self._dependencies if self._dependencies else None,
                **self.kwargs
            )
        return self.job_id


# Modified DAGContext
class DAGContext:
    def task(self, func: Callable, name: str = None, **kwargs) -> Task:
        """Create a Task object (lazy enqueue)."""
        if name is None:
            name = func.__name__
        
        return Task(self, func, name, **kwargs)
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """On exit, submit all tasks in dependency order."""
        if exc_type is None and not self._submitted:
            # Build execution graph from Task dependencies
            for task_name, task in self._tasks.items():
                task.submit()
            
            # Continue with normal submission
            super().__exit__(exc_type, exc_val, exc_tb)
```

**Effort:** Low (1-2 days)

---

## 🎯 Phase 5: Sensors & Advanced Triggers (Week 6)

### 5.1 Sensor Framework

**Target State:**
```python
from queuack.sensors import FileSensor, TimeSensor, ExternalTaskSensor

with queue.dag("wait_for_data") as dag:
    # Wait for file to exist
    wait_file = FileSensor(
        name="wait_for_file",
        filepath="/data/input.csv",
        timeout=3600,  # 1 hour
        poke_interval=60  # Check every minute
    )
    
    # Wait for specific time
    wait_time = TimeSensor(
        name="wait_until_9am",
        target_time="09:00:00"
    )
    
    # Wait for external task
    wait_upstream = ExternalTaskSensor(
        name="wait_upstream",
        external_dag_id="upstream_dag",
        external_task_id="export_data"
    )
    
    process = dag.task(process_data, name="process")
    
    [wait_file, wait_time, wait_upstream] >> process
```

**Implementation:**

```python
# queuack/sensors.py
from abc import ABC, abstractmethod
import time
from pathlib import Path

class BaseSensor(ABC):
    """Base class for all sensors."""
    
    def __init__(self, name: str, timeout: int = 3600, 
                 poke_interval: int = 60, mode: str = 'poke'):
        """
        Args:
            name: Sensor task name
            timeout: Maximum time to wait (seconds)
            poke_interval: Time between checks (seconds)
            mode: 'poke' (blocking) or 'reschedule' (release worker)
        """
        self.name = name
        self.timeout = timeout
        self.poke_interval = poke_interval
        self.mode = mode
    
    @abstractmethod
    def poke(self, context) -> bool:
        """Check if condition is met. Return True when ready."""
        pass
    
    def execute(self, **context):
        """Execute sensor logic."""
        start_time = time.time()
        
        while True:
            elapsed = time.time() - start_time
            
            if elapsed > self.timeout:
                raise TimeoutError(f"Sensor {self.name} timed out after {self.timeout}s")
            
            # Check condition
            if self.poke(context):
                return True
            
            # Wait before next check
            if self.mode == 'poke':
                time.sleep(self.poke_interval)
            else:
                # Reschedule mode: release worker and requeue
                raise SensorRescheduleException(self.poke_interval)


class FileSensor(BaseSensor):
    """Wait for file to exist."""
    
    def __init__(self, filepath: str, **kwargs):
        super().__init__(**kwargs)
        self.filepath = Path(filepath)
    
    def poke(self, context) -> bool:
        exists = self.filepath.exists()
        if exists:
            logger.info(f"File {self.filepath} found!")
        return exists


class TimeSensor(BaseSensor):
    """Wait until specific time."""
    
    def __init__(self, target_time: str, **kwargs):
        super().__init__(**kwargs)
        # Parse HH:MM:SS
        parts = target_time.split(':')
        self.target_hour = int(parts[0])
        self.target_minute = int(parts[1]) if len(parts) > 1 else 0
        self.target_second = int(parts[2]) if len(parts) > 2 else 0
    
    def poke(self, context) -> bool:
        now = datetime.now()
        target = now.replace(
            hour=self.target_hour,
            minute=self.target_minute,
            second=self.target_second,
            microsecond=0
        )
        
        # If target time passed today, wait for tomorrow
        if now > target:
            target += timedelta(days=1)
        
        return now >= target


class ExternalTaskSensor(BaseSensor):
    """Wait for external DAG task to complete."""
    
    def __init__(self, external_dag_id: str, external_task_id: str, 
                 queue: DuckQueue, **kwargs):
        super().__init__(**kwargs)
        self.external_dag_id = external_dag_id
        self.external_task_id = external_task_id
        self.queue = queue
    
    def poke(self, context) -> bool:
        with self.queue._db_lock:
            result = self.queue.conn.execute("""
                SELECT status FROM jobs
                WHERE dag_run_id IN (
                    SELECT id FROM dag_runs 
                    WHERE name = ?
                    ORDER BY created_at DESC 
                    LIMIT 1
                )
                AND node_name = ?
            """, [self.external_dag_id, self.external_task_id]).fetchone()
        
        if result and result[0] == 'done':
            logger.info(f"External task {self.external_dag_id}.{self.external_task_id} completed")
            return True
        
        return False


class SensorRescheduleException(Exception):
    """Raised to reschedule sensor instead of blocking."""
    
    def __init__(self, delay: int):
        self.delay = delay
        super().__init__(f"Reschedule after {delay}s")


# Integration with DAGContext
class DAGContext:
    def sensor(self, sensor: BaseSensor, **kwargs) -> Task:
        """Add sensor as a task."""
        return self.task(sensor.execute, name=sensor.name, **kwargs)
```

**Effort:** High (5-6 days)

---

## 🎯 Phase 6: Retry Logic & Callbacks (Week 7)

### 6.1 Exponential Backoff & Callbacks

**Target State:**
```python
from queuack import RetryPolicy

def send_email_on_failure(context):
    """Callback on task failure."""
    task = context['task_instance']
    print(f"Task {task.task_id} failed on attempt {context['attempt']}")
    # Send email, Slack notification, etc.

with queue.dag("resilient_pipeline") as dag:
    flaky_task = dag.task(
        flaky_api_call,
        name="api_call",
        retry_policy=RetryPolicy(
            max_attempts=5,
            initial_delay=60,  # 1 minute
            max_delay=3600,    # 1 hour
            backoff_factor=2.0,  # Exponential
            retry_on=[requests.RequestException, TimeoutError]
        ),
        on_failure_callback=send_email_on_failure,
        on_success_callback=lambda ctx: print("Success!"),
        on_retry_callback=lambda ctx: print(f"Retry #{ctx['attempt']}")
    )
```

**Implementation:**

```python
# queuack/retry.py
@dataclass
class RetryPolicy:
    """Retry configuration."""
    max_attempts: int = 3
    initial_delay: int = 60  # seconds
    max_delay: int = 3600
    backoff_factor: float = 2.0  # Exponential
    retry_on: List[type] = None  # Exception types to retry
    
    def get_delay(self, attempt: int) -> int:
        """Calculate delay for given attempt."""
        if attempt <= 0:
            return 0
        
        delay = self.initial_delay * (self.backoff_factor ** (attempt - 1))
        return min(int(delay), self.max_delay)
    
    def should_retry(self, exception: Exception) -> bool:
        """Check if exception is retryable."""
        if not self.retry_on:
            return True  # Retry all exceptions
        
        return any(isinstance(exception, exc_type) for exc_type in self.retry_on)


# Modified Job execution
@dataclass
class Job:
    # Add new fields
    retry_policy: Optional[RetryPolicy] = None
    on_success_callback: Optional[Callable] = None
    on_failure_callback: Optional[Callable] = None
    on_retry_callback: Optional[Callable] = None
    
    def execute(self, context: Optional[ExecutionContext] = None) -> Any:
        """Execute with retry logic and callbacks."""
        func = pickle.loads(self.func)
        args = pickle.loads(self.args)
        kwargs = pickle.loads(self.kwargs)
        
        # Inject context
        if context:
            import inspect
            sig = inspect.signature(func)
            if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                kwargs.update(context.to_dict())
        
        try:
            result = func(*args, **kwargs)
            
            # Success callback
            if self.on_success_callback and context:
                self.on_success_callback(context.to_dict())
            
            # Auto-push to XCom
            if context and result is not None:
                context.task_instance.xcom_push('return_value', result)
            
            return result
        
        except Exception as e:
            # Check if should retry
            if self.retry_policy and self.attempts < self.retry_policy.max_attempts:
                if self.retry_policy.should_retry(e):
                    # Retry callback
                    if self.on_retry_callback and context:
                        self.on_retry_callback(context.to_dict())
                    
                    # Calculate delay
                    delay = self.retry_policy.get_delay(self.attempts)
                    
                    raise RetryException(delay, str(e))
            
            # Failure callback
            if self.on_failure_callback and context:
                try:
                    self.on_failure_callback(context.to_dict())
                except Exception as cb_error:
                    logger.error(f"Callback error: {cb_error}")
            
            raise


class RetryException(Exception):
    """Signal that task should be retried."""
    def __init__(self, delay: int, original_error: str):
        self.delay = delay
        self.original_error = original_error
        super().__init__(f"Retry after {delay}s: {original_error}")


# Modified Worker to handle RetryException
class Worker:
    def _execute_job(self, job: Job, job_num: int):
        """Execute with retry handling."""
        try:
            # Build context
            context = self._build_context(job)
            result = job.execute(context=context)
            self.queue.ack(job.id, result=result)
            
        except RetryException as e:
            # Requeue with delay
            logger.info(f"Job {job.id[:8]} retry #{job.attempts} in {e.delay}s")
            
            self.queue.conn.execute("""
                UPDATE jobs
                SET 
                    status = 'delayed',
                    execute_after = ?,
                    error = ?,
                    claimed_at = NULL,
                    claimed_by = NULL
                WHERE id = ?
            """, [datetime.now() + timedelta(seconds=e.delay), e.original_error, job.id])
        
        except Exception as e:
            # Permanent failure
            error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            self.queue.ack(job.id, error=error_msg)
    
    def _build_context(self, job: Job) -> ExecutionContext:
        """Build execution context for job."""
        return ExecutionContext(
            task_instance=TaskInstance(
                job_id=job.id,
                dag_run_id=job.dag_run_id,
                task_id=job.node_name,
                execution_date=job.created_at,
                xcom_manager=self.queue._xcom_manager
            ),
            dag_run_id=job.dag_run_id,
            execution_date=job.created_at,
            dag_name=job.dag_run_id,  # TODO: Store actual DAG name
            task_id=job.node_name,
            attempt=job.attempts
        )
```

**Database Schema Changes:**
```sql
ALTER TABLE jobs ADD COLUMN retry_policy_json TEXT;
ALTER TABLE jobs ADD COLUMN callbacks_json TEXT;
```

**Effort:** Medium (3-4 days)

---

## 🎯 Phase 7: Pools & Resource Management (Week 8)

### 7.1 Resource Pools

**Target State:**
```python
from queuack import Pool

# Define resource pools
queue.create_pool('gpu', slots=2, description='GPU resources')
queue.create_pool('api_rate_limit', slots=10, description='API calls per minute')

with queue.dag("ml_training") as dag:
    # Task requires GPU slot
    train = dag.task(
        train_model,
        name="train",
        pool='gpu',  # Blocks until GPU available
        priority_weight=10
    )
    
    # Multiple API calls share rate limit pool
    for i in range(20):
        api_call = dag.task(
            call_api,
            name=f"api_{i}",
            pool='api_rate_limit'  # Max 10 concurrent
        )
```

**Implementation:**

```python
# queuack/pools.py
@dataclass
class Pool:
    """Resource pool with limited slots."""
    name: str
    slots: int
    description: str = ""
    occupied_slots: int = 0
    
    def has_capacity(self) -> bool:
        return self.occupied_slots < self.slots
    
    def acquire(self) -> bool:
        if self.has_capacity():
            self.occupied_slots += 1
            return True
        return False
    
    def release(self):
        if self.occupied_slots > 0:
            self.occupied_slots -= 1


class PoolManager:
    """Manages resource pools."""
    
    def __init__(self, queue: DuckQueue):
        self.queue = queue
        self._pools: Dict[str, Pool] = {}
        self._load_pools()
    
    def create_pool(self, name: str, slots: int, description: str = ""):
        """Create or update a pool."""
        with self.queue._db_lock:
            self.queue.conn.execute("""
                INSERT OR REPLACE INTO pools (name, slots, description)
                VALUES (?, ?, ?)
            """, [name, slots, description])
        
        self._pools[name] = Pool(name, slots, description)
    
    def get_pool(self, name: str) -> Optional[Pool]:
        """Get pool by name."""
        return self._pools.get(name)
    
    def _load_pools(self):
        """Load pools from database."""
        with self.queue._db_lock:
            results = self.queue.conn.execute("""
                SELECT name, slots, description FROM pools
            """).fetchall()
        
        for name, slots, desc in results:
            self._pools[name] = Pool(name, slots, desc)
    
    def can_claim(self, pool_name: str) -> bool:
        """Check if pool has capacity."""
        pool = self._pools.get(pool_name)
        if not pool:
            return True  # No pool restriction
        
        with self.queue._db_lock:
            # Count jobs using this pool
            result = self.queue.conn.execute("""
                SELECT COUNT(*) FROM jobs
                WHERE pool = ? AND status = 'claimed'
            """, [pool_name]).fetchone()
            
            occupied = result[0] if result else 0
            return occupied < pool.slots


# Modified claim logic in DuckQueue
class DuckQueue:
    def claim(self, queue: str = None, worker_id: str = None, 
              claim_timeout: int = 300) -> Optional[Job]:
        """Claim with pool awareness."""
        queue = queue or self.default_queue
        worker_id = worker_id or self._generate_worker_id()
        now = datetime.now()
        
        with self._db_lock:
            # Promote delayed jobs
            self.conn.execute("""
                UPDATE jobs SET status = 'pending'
                WHERE status = 'delayed' AND execute_after <= ?
            """, [now])
            
            # Atomic claim with pool check
            result = self.conn.execute("""
                UPDATE jobs
                SET 
                    status = 'claimed',
                    claimed_at = ?,
                    claimed_by = ?,
                    attempts = attempts + 1
                WHERE id = (
                    SELECT j.id FROM jobs AS j
                    WHERE j.queue = ?
                    AND (j.status = 'pending' OR (j.status = 'claimed' AND j.claimed_at < ?))
                    AND j.attempts < j.max_attempts
                    AND (j.execute_after IS NULL OR j.execute_after <= ?)
                    AND (
                        -- Pool check
                        j.pool IS NULL OR j.pool IN (
                            SELECT name FROM pools p
                            WHERE (
                                SELECT COUNT(*) FROM jobs 
                                WHERE pool = p.name AND status = 'claimed'
                            ) < p.slots
                        )
                    )
                    AND (
                        -- Dependency check (existing logic)
                        NOT EXISTS (SELECT 1 FROM job_dependencies WHERE child_job_id = j.id)
                        OR (j.dependency_mode = 'all' AND NOT EXISTS (...))
                        OR (j.dependency_mode = 'any' AND EXISTS (...))
                    )
                    ORDER BY j.priority DESC, j.created_at ASC
                    LIMIT 1
                )
                RETURNING *
            """, [now, worker_id, queue, now - timedelta(seconds=claim_timeout), now]).fetchone()
            
            # ... rest of claim logic
```

**Database Schema Changes:**
```sql
CREATE TABLE pools (
    name VARCHAR PRIMARY KEY,
    slots INTEGER NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE jobs ADD COLUMN pool VARCHAR REFERENCES pools(name);
CREATE INDEX idx_jobs_pool ON jobs(pool, status);
```

**Effort:** Medium (4-5 days)

---

## 🎯 Phase 8: Task Logs & Monitoring (Week 9)

### 8.1 Task-Level Logging

**Target State:**
```python
def my_task(**context):
    logger = context['task_instance'].get_logger()
    
    logger.info("Starting task")
    logger.warning("This is a warning")
    logger.error("This is an error")
    
    # Logs automatically captured and stored per task
```

**Implementation:**

```python
# queuack/logging.py
import logging
import io
from contextlib import redirect_stdout, redirect_stderr

class TaskLogger:
    """Logger that captures task output."""
    
    def __init__(self, job_id: str, task_id: str, dag_run_id: str, queue: DuckQueue):
        self.job_id = job_id
        self.task_id = task_id
        self.dag_run_id = dag_run_id
        self.queue = queue
        
        # Create logger
        self.logger = logging.getLogger(f"queuack.task.{task_id}")
        self.logger.setLevel(logging.INFO)
        
        # Capture to string buffer
        self.log_buffer = io.StringIO()
        handler = logging.StreamHandler(self.log_buffer)
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        self.logger.addHandler(handler)
    
    def get_logs(self) -> str:
        """Get captured logs."""
        return self.log_buffer.getvalue()
    
    def save_logs(self):
        """Persist logs to database."""
        logs = self.get_logs()
        
        with self.queue._db_lock:
            self.queue.conn.execute("""
                INSERT INTO job_logs (job_id, dag_run_id, node_name, logs, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, [self.job_id, self.dag_run_id, self.task_id, logs, datetime.now()])


# Modified TaskInstance
@dataclass
class TaskInstance:
    # ... existing fields
    _logger: Optional[TaskLogger] = None
    
    def get_logger(self) -> logging.Logger:
        """Get task-specific logger."""
        if not self._logger:
            self._logger = TaskLogger(
                self.job_id,
                self.task_id,
                self.dag_run_id,
                self.xcom_manager.queue
            )
        return self._logger.logger


# Modified Job execution
class Job:
    def execute(self, context: Optional[ExecutionContext] = None) -> Any:
        """Execute with log capture."""
        func = pickle.loads(self.func)
        args = pickle.loads(self.args)
        kwargs = pickle.loads(self.kwargs)
        
        # Setup logger
        if context:
            task_logger = context.task_instance.get_logger()
            
            # Redirect stdout/stderr
            stdout_buffer = io.StringIO()
            stderr_buffer = io.StringIO()
            
            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                try:
                    # Inject context
                    if any(p.kind == inspect.Parameter.VAR_KEYWORD 
                           for p in inspect.signature(func).parameters.values()):
                        kwargs.update(context.to_dict())
                    
                    task_logger.info(f"Executing {self.node_name}")
                    result = func(*args, **kwargs)
                    task_logger.info(f"Completed {self.node_name}")
                    
                    # Save logs
                    context.task_instance._logger.save_logs()
                    
                    return result
                
                except Exception as e:
                    task_logger.error(f"Failed: {e}")
                    context.task_instance._logger.save_logs()
                    raise
```

**Database Schema Changes:**
```sql
CREATE TABLE job_logs (
    id VARCHAR PRIMARY KEY DEFAULT (uuid()),
    job_id VARCHAR NOT NULL,
    dag_run_id VARCHAR,
    node_name VARCHAR,
    logs TEXT,
    created_at TIMESTAMP NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE INDEX idx_job_logs_job ON job_logs(job_id);
CREATE INDEX idx_job_logs_dag_run ON job_logs(dag_run_id, node_name);
```

**Effort:** Medium (3-4 days)

---

## 🎯 Phase 9: Backfill & Historical Execution (Week 10)

### 9.1 Backfill Mechanism

**Target State:**
```bash
# Backfill DAG for date range
queuack dags backfill my_dag \
    --start-date 2024-01-01 \
    --end-date 2024-01-31 \
    --clear  # Clear existing runs first
```

**Implementation:**

```python
# queuack/backfill.py
class BackfillRunner:
    """Handles backfilling DAGs for historical dates."""
    
    def __init__(self, queue: DuckQueue):
        self.queue = queue
    
    def backfill(
        self,
        dag_name: str,
        start_date: datetime,
        end_date: datetime,
        clear: bool = False,
        max_active_runs: int = 1
    ):
        """Backfill DAG for date range."""
        
        # Get DAG factory
        if dag_name not in self.queue._scheduler.scheduled_dags:
            raise ValueError(f"DAG '{dag_name}' not found")
        
        dag_factory, schedule = self.queue._scheduler.scheduled_dags[dag_name]
        
        # Clear existing runs if requested
        if clear:
            self._clear_runs(dag_name, start_date, end_date)
        
        # Generate execution dates
        execution_dates = self._generate_execution_dates(schedule, start_date, end_date)
        
        logger.info(f"Backfilling {len(execution_dates)} runs for {dag_name}")
        
        # Execute each date
        active_runs = []
        for exec_date in execution_dates:
            # Wait if too many active
            while len(active_runs) >= max_active_runs:
                active_runs = [r for r in active_runs if not r.is_complete()]
                time.sleep(5)
            
            # Trigger DAG with execution_date
            dag = dag_factory()
            
            # Override execution date in context
            dag._execution_date = exec_date
            run_id = dag.submit()
            
            active_runs.append(DAGRun(self.queue, run_id))
            logger.info(f"Started backfill run for {exec_date}")
        
        # Wait for all to complete
        for run in active_runs:
            while not run.is_complete():
                time.sleep(5)
        
        logger.info(f"Backfill complete for {dag_name}")
    
    def _clear_runs(self, dag_name: str, start_date: datetime, end_date: datetime):
        """Clear existing runs in date range."""
        with self.queue._db_lock:
            self.queue.conn.execute("""
                DELETE FROM jobs
                WHERE dag_run_id IN (
                    SELECT id FROM dag_runs
                    WHERE name = ?
                    AND created_at BETWEEN ? AND ?
                )
            """, [dag_name, start_date, end_date])
            
            self.queue.conn.execute("""
                DELETE FROM dag_runs
                WHERE name = ? AND created_at BETWEEN ? AND ?
            """, [dag_name, start_date, end_date])
    
    def _generate_execution_dates(
        self,
        schedule: Schedule,
        start_date: datetime,
        end_date: datetime
    ) -> List[datetime]:
        """Generate list of execution dates."""
        dates = []
        current = start_date
        
        while current <= end_date:
            dates.append(current)
            next_date = schedule.get_next_run(current)
            
            if not next_date or next_date <= current:
                break
            
            current = next_date
        
        return dates


# Add to CLI
@dags.command('backfill')
@click.argument('dag_name')
@click.option('--start-date', required=True)
@click.option('--end-date', required=True)
@click.option('--clear', is_flag=True)
@click.option('--max-active-runs', default=1)
@click.pass_context
def backfill_dag(ctx, dag_name, start_date, end_date, clear, max_active_runs):
    """Backfill DAG for date range."""
    queue = ctx.obj['queue']
    
    start = datetime.fromisoformat(start_date)
    end = datetime.fromisoformat(end_date)
    
    runner = BackfillRunner(queue)
    runner.backfill(dag_name, start, end, clear, max_active_runs)
```

**Effort:** High (5-6 days)

---

## 📋 Implementation Priority Matrix

| Phase | Feature | User Impact | Technical Complexity | Dependencies | Recommended Order |
|-------|---------|-------------|---------------------|--------------|-------------------|
| 1 | Scheduling | 🔴 Critical | Medium | croniter | **1st** |
| 2 | XCom | 🔴 Critical | Medium | - | **2nd** |
| 2 | Context | 🔴 Critical | Medium | XCom | **2nd** |
| 3 | CLI | 🔴 Critical | Low | - | **3rd** |
| 4 | `>>` Operator | 🟡 High | Low | - | **4th** |
| 6 | Retry Logic | 🟡 High | Medium | - | **5th** |
| 5 | Sensors | 🟡 High | High | Context | **6th** |
| 7 | Pools | 🟡 High | High | - | **7th** |
| 8 | Logging | 🟡 High | Medium | Context | **8th** |
| 9 | Backfill | 🟢 Medium | High | Scheduling | **9th** |

---

## 🚀 Suggested Implementation Sequence

### **Sprint 1 (Weeks 1-3): Core Foundation**
1. ✅ Scheduling framework
2. ✅ XCom + Execution Context
3. ✅ Enhanced CLI

**Deliverable:** Scheduled DAGs with data passing

### **Sprint 2 (Weeks 4-6): Developer Experience**
4. ✅ `>>` operator & syntactic sugar
5. ✅ Retry policies with callbacks
6. ✅ Sensor framework

**Deliverable:** Airflow-like DAG authoring

### **Sprint 3 (Weeks 7-10): Production Features**
7. ✅ Resource pools
8. ✅ Task logging
9. ✅ Backfill mechanism

**Deliverable:** Production-ready orchestration

---

## 📦 Additional Dependencies

```toml
# pyproject.toml additions
[dependencies]
croniter = "^2.0.0"  # Cron scheduling
click = "^8.1.0"     # CLI
tabulate = "^0.9.0"  # CLI tables
colorama = "^0.4.0"  # Colored output
```

---

## 🎓 Migration Path for Existing Users

### Step 1: Backward Compatibility
All existing code continues to work:
```python
# Old API still works
with queue.dag("etl") as dag:
    extract = dag.enqueue(extract_data, name="extract")
```

### Step 2: Gradual Adoption
New features are opt-in:
```python
# Add scheduling when ready
@queue.scheduled_dag("etl", schedule=Schedule.daily())
def etl_dag():
    with queue.dag("etl") as dag:
        extract = dag.enqueue(extract_data, name="extract")
    return dag
```

### Step 3: Full Migration
Eventually adopt all features:
```python
@queue.scheduled_dag("etl", schedule=Schedule.daily())
def etl_dag():
    with queue.dag("etl") as dag:
        extract = dag.task(extract_data, name="extract")
        transform = dag.task(transform_data, name="transform")
        
        extract >> transform  # New syntax
    return dag
```

---

## 🧪 Testing Strategy

### Unit Tests
- Each component tested in isolation
- Mock database for fast tests
- Property-based testing for schedule calculations

### Integration Tests
- End-to-end DAG execution
- Scheduler correctness
- XCom data flow
- Retry behavior

### Performance Tests
- Benchmark scheduling overhead
- Pool contention scenarios
- Large DAG execution (100+ tasks)

---

## 📊 Success Metrics

| Metric | Current | Target | How to Measure |
|--------|---------|--------|----------------|
| Lines to define DAG | ~15 | ~10 | Code samples |
| Time to first DAG run | Manual | <5 min | Onboarding test |
| Scheduling accuracy | N/A | ±30s | Schedule deviation |
| XCom throughput | N/A | 1000 msg/s | Benchmark |
| Task retry latency | Fixed | Configurable | Retry tests |
| CLI command coverage | 20% | 80% | Command count |

---

## 🎯 Final Assessment

**Current State:** Queuack is a solid job queue with basic DAG support

**Target State:** Airflow-like orchestration without the complexity

**Gap:** ~10 weeks of focused development across 9 phases

**Biggest Wins:**
1. 🔴 Scheduling → Enables autonomous workflows
2. 🔴 XCom → Enables data pipelines
3. 🔴 Context → Enables task introspection
4. 🟡 CLI → Enables operational management

**Recommended Path:**
- Start with **Phase 1-3** (4 weeks) → 80% of Airflow DX
- Add **Phase 4-6** (3 weeks) → Feature parity
- Polish with **Phase 7-9** (3 weeks) → Production ready
