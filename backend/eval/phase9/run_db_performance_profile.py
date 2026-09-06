"""Phase 9.12 read-only database performance profiler."""

import argparse
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from db import (
    execute_query,
    get_connection,
    get_table_metadata,
    prepare_sql,
)


DEFAULT_SQL = 'SELECT "PetType" FROM pets_1."Pets";'
DEFAULT_RUNS = 50

RESULTS_DIR = Path("eval/phase9/results")


def measure(func, runs):
    timings = []

    for _ in range(runs):
        start = time.perf_counter()
        func()
        timings.append(
            (time.perf_counter() - start) * 1000
        )

    return timings


def summarize(values):
    ordered = sorted(values)

    p95_index = max(
        0,
        min(
            len(ordered) - 1,
            int(0.95 * len(ordered)) - 1,
        ),
    )

    return {
        "mean_ms": round(statistics.mean(values), 3),
        "median_ms": round(statistics.median(values), 3),
        "p95_ms": round(ordered[p95_index], 3),
        "min_ms": round(min(values), 3),
        "max_ms": round(max(values), 3),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--experiment-id",
        required=True,
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUNS,
    )
    args = parser.parse_args()

    if args.runs < 1:
        raise SystemExit("--runs must be >= 1")

    sql = DEFAULT_SQL

    # Warm up local imports, PostgreSQL and metadata paths once.
    get_table_metadata()
    prepare_sql(sql)
    execute_query(sql)

    metadata = measure(
        get_table_metadata,
        args.runs,
    )

    preparation = measure(
        lambda: prepare_sql(sql),
        args.runs,
    )

    def connect_only():
        conn = get_connection()
        conn.close()

    connection = measure(
        connect_only,
        args.runs,
    )

    execution = measure(
        lambda: execute_query(sql),
        args.runs,
    )

    result = {
        "phase": "9.12",
        "experiment_id": args.experiment_id,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "runs_per_operation": args.runs,
        "sql": sql,
        "read_only": True,
        "metrics": {
            "metadata_lookup": summarize(metadata),
            "prepare_sql": summarize(preparation),
            "connection_only": summarize(connection),
            "full_execute_query": summarize(execution),
        },
    }

    RESULTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    output = RESULTS_DIR / (
        f"{args.experiment_id}.json"
    )

    output.write_text(
        json.dumps(
            result,
            indent=2,
        )
        + "\n"
    )

    print()
    print("=" * 72)
    print("PHASE 9.12 DATABASE PERFORMANCE PROFILE")
    print("=" * 72)

    for name, metrics in result["metrics"].items():
        print(
            f"{name:<20} "
            f"mean={metrics['mean_ms']:8.3f} ms  "
            f"median={metrics['median_ms']:8.3f} ms  "
            f"p95={metrics['p95_ms']:8.3f} ms"
        )

    print()
    print(f"Results saved: {output}")


if __name__ == "__main__":
    main()
