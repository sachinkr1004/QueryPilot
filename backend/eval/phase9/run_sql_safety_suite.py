"""
Phase 9.9 production SQL safety regression suite.

Validates:
- AST-level read-only SQL policy
- multi-statement rejection
- DML / DDL rejection
- writable CTE rejection
- SELECT INTO rejection
- row-lock rejection
- application execution-path blocking
- PostgreSQL read-only enforcement
- statement-timeout enforcement
"""

import time

from db import (
    execute_query,
    get_connection,
    is_safe_sql,
)


passed = 0
failed = 0


def record(name, ok, detail=""):
    global passed, failed

    if ok:
        passed += 1
        print(f"✅ {name}")
    else:
        failed += 1
        print(f"❌ {name}")
        if detail:
            print(f"   {detail}")


def check_validator(name, sql, expected):
    actual = is_safe_sql(sql)

    record(
        name,
        actual == expected,
        f"expected={expected}, actual={actual}",
    )


# ============================================================
# 1. AST VALIDATOR TESTS
# ============================================================

validator_tests = [
    # Legitimate read-only queries
    ("validator_simple_select", "SELECT 1", True),
    (
        "validator_cte_select",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        True,
    ),
    (
        "validator_union",
        "SELECT 1 UNION SELECT 2",
        True,
    ),
    (
        "validator_intersect",
        "SELECT 1 INTERSECT SELECT 1",
        True,
    ),
    (
        "validator_except",
        "SELECT 1 EXCEPT SELECT 2",
        True,
    ),
    (
        "validator_subquery",
        "SELECT * FROM (SELECT 1 AS x) t",
        True,
    ),
    (
        "validator_leading_comment",
        "-- safe comment\nSELECT 1",
        True,
    ),

    # Multiple statements
    (
        "validator_two_selects",
        "SELECT 1; SELECT 2",
        False,
    ),
    (
        "validator_select_then_delete",
        "SELECT 1; DELETE FROM x",
        False,
    ),

    # DML / DDL
    ("validator_insert", "INSERT INTO x VALUES (1)", False),
    ("validator_update", "UPDATE x SET a = 1", False),
    ("validator_delete", "DELETE FROM x", False),
    ("validator_create", "CREATE TABLE x(a int)", False),
    (
        "validator_alter",
        "ALTER TABLE x ADD COLUMN b int",
        False,
    ),
    ("validator_drop", "DROP TABLE x", False),
    ("validator_truncate", "TRUNCATE TABLE x", False),
    (
        "validator_merge",
        "MERGE INTO target t "
        "USING source s ON t.id = s.id "
        "WHEN MATCHED THEN UPDATE SET value = s.value",
        False,
    ),

    # Writable CTEs
    (
        "validator_delete_cte",
        "WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x",
        False,
    ),
    (
        "validator_insert_cte",
        "WITH x AS "
        "(INSERT INTO t VALUES (1) RETURNING *) "
        "SELECT * FROM x",
        False,
    ),
    (
        "validator_update_cte",
        "WITH x AS "
        "(UPDATE t SET a = 1 RETURNING *) "
        "SELECT * FROM x",
        False,
    ),

    # SELECT side effects / locking
    (
        "validator_select_into",
        "SELECT * INTO new_table FROM old_table",
        False,
    ),
    (
        "validator_nested_select_into",
        "(SELECT * INTO new_table FROM old_table) "
        "UNION SELECT * FROM old_table",
        False,
    ),
    (
        "validator_for_update",
        "SELECT * FROM x FOR UPDATE",
        False,
    ),
    (
        "validator_for_share",
        "SELECT * FROM x FOR SHARE",
        False,
    ),

    # Whitespace bypass regressions from old validator
    (
        "validator_delete_newline",
        "SELECT 1; DELETE\nFROM x",
        False,
    ),
    (
        "validator_drop_tab",
        "SELECT 1; DROP\tTABLE x",
        False,
    ),

    # Non-query commands
    ("validator_set", "SET search_path TO public", False),
    ("validator_begin", "BEGIN", False),
    ("validator_commit", "COMMIT", False),

    # Invalid / empty input
    ("validator_empty", "", False),
    ("validator_invalid_sql", "SELECT FROM WHERE", False),
]


for name, sql, expected in validator_tests:
    check_validator(name, sql, expected)


# ============================================================
# 2. APPLICATION EXECUTION-PATH TESTS
# ============================================================

try:
    rows = execute_query("SELECT 1;")
    record(
        "execute_safe_select",
        rows == [(1,)],
        f"unexpected rows={rows!r}",
    )
except Exception as exc:
    record(
        "execute_safe_select",
        False,
        f"{type(exc).__name__}: {exc}",
    )


execution_block_tests = [
    (
        "execute_blocks_delete",
        'DELETE FROM pets_1."Student";',
    ),
    (
        "execute_blocks_multi_statement",
        'SELECT 1; DROP TABLE pets_1."Student";',
    ),
    (
        "execute_blocks_select_into",
        'SELECT * INTO temp_copy FROM pets_1."Student";',
    ),
    (
        "execute_blocks_for_update",
        'SELECT * FROM pets_1."Student" FOR UPDATE;',
    ),
]


for name, sql in execution_block_tests:
    try:
        execute_query(sql)
        record(
            name,
            False,
            "unsafe SQL reached successful execution",
        )
    except ValueError:
        record(name, True)
    except Exception as exc:
        record(
            name,
            False,
            "expected QueryPilot ValueError, got "
            f"{type(exc).__name__}: {exc}",
        )


# ============================================================
# 3. POSTGRESQL DEFENSE-IN-DEPTH TESTS
# ============================================================

conn = None
cursor = None

try:
    conn = get_connection()
    conn.set_session(readonly=True)
    cursor = conn.cursor()

    cursor.execute("SHOW transaction_read_only;")
    readonly_value = cursor.fetchone()[0]

    record(
        "postgres_readonly_enabled",
        readonly_value == "on",
        f"transaction_read_only={readonly_value!r}",
    )

    try:
        cursor.execute(
            "CREATE TEMP TABLE "
            "querypilot_safety_should_not_exist "
            "(id INTEGER);"
        )
        record(
            "postgres_blocks_write",
            False,
            "CREATE TABLE unexpectedly succeeded",
        )
    except Exception as exc:
        record(
            "postgres_blocks_write",
            True,
            f"{type(exc).__name__}: {exc}",
        )
        conn.rollback()

finally:
    if cursor is not None:
        cursor.close()
    if conn is not None:
        conn.close()


# ============================================================
# 4. STATEMENT TIMEOUT TEST
# ============================================================

conn = None
cursor = None

try:
    conn = get_connection()
    conn.set_session(readonly=True)
    cursor = conn.cursor()

    cursor.execute("SET LOCAL statement_timeout = '200ms';")

    start = time.perf_counter()

    try:
        cursor.execute("SELECT pg_sleep(1);")

        record(
            "postgres_statement_timeout",
            False,
            "pg_sleep(1) was not cancelled",
        )

    except Exception as exc:
        elapsed = time.perf_counter() - start

        record(
            "postgres_statement_timeout",
            elapsed < 0.8,
            f"{type(exc).__name__}, elapsed={elapsed:.3f}s",
        )

        conn.rollback()

finally:
    if cursor is not None:
        cursor.close()
    if conn is not None:
        conn.close()


# ============================================================
# FINAL RESULT
# ============================================================

total = passed + failed

print()
print("=" * 60)
print("PHASE 9.9 SQL SAFETY SUITE")
print("=" * 60)
print(f"TOTAL:  {total}")
print(f"PASSED: {passed}")
print(f"FAILED: {failed}")

if failed:
    print("❌ SAFETY SUITE FAILED")
    raise SystemExit(1)

print("✅ ALL SQL SAFETY TESTS PASSED")
