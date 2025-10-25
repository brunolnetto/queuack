"""Migrate jobs between queues or databases."""

import pickle

from queuack import DuckQueue


def migrate_queue(source_db: str, target_db: str, queue_name: str = None):
    """Migrate jobs from one database to another."""
    source = DuckQueue(source_db)
    target = DuckQueue(target_db)

    if queue_name:
        query = "SELECT * FROM jobs WHERE queue = ? AND status = 'pending'"
        results = source.conn.execute(query, [queue_name]).fetchall()
    else:
        results = source.conn.execute(
            "SELECT * FROM jobs WHERE status = 'pending'"
        ).fetchall()

    source.conn.commit()

    migrated = 0
    for row in results:
        # Deserialize and re-enqueue
        func = pickle.loads(row[1])  # func column
        args = pickle.loads(row[2])  # args column
        kwargs = pickle.loads(row[3])  # kwargs column

        target.enqueue(
            func,
            args=args,
            kwargs=kwargs,
            queue=row[4],  # queue column
            priority=row[6],  # priority column
        )
        migrated += 1

    print(f"✓ Migrated {migrated} jobs from {source_db} to {target_db}")


if __name__ == "__main__":
    migrate_queue("old_queue.db", "new_queue.db")
