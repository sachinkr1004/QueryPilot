import argparse
import json
import re
import sqlite3
from pathlib import Path

from psycopg2 import sql

from db import get_connection
from finetuning.spider_context import get_sqlite_database_path


BASE_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = BASE_DIR / "final_test_manifest.json"


def map_sqlite_type(declared_type: str) -> str:
    declared = declared_type.strip().upper()

    if declared in {"INT", "INTEGER"}:
        return "INTEGER"

    if declared in {"REAL", "DOUBLE"}:
        return "DOUBLE PRECISION"

    decimal_match = re.fullmatch(
        r"DECIMAL\((\d+),\s*(\d+)\)",
        declared,
    )
    if decimal_match:
        precision, scale = decimal_match.groups()
        return f"NUMERIC({precision},{scale})"

    char_match = re.fullmatch(
        r"CHAR\((\d+)\)",
        declared,
    )
    if char_match:
        return "TEXT"

    varchar_match = re.fullmatch(
        r"VARCHAR\((\d+)\)",
        declared,
    )
    if varchar_match:
        return "TEXT"

    if declared == "TEXT":
        return "TEXT"

    if declared == "DATE":
        return "DATE"

    if declared == "DATETIME":
        return "TIMESTAMP"

    datetime_match = re.fullmatch(
        r"DATETIME\((\d+)\)",
        declared,
    )
    if datetime_match:
        return f"TIMESTAMP({datetime_match.group(1)})"

    raise ValueError(
        f"Unsupported SQLite type: {declared_type}"
    )


def get_final_database_ids():
    manifest = json.loads(
        MANIFEST_PATH.read_text(
            encoding="utf-8"
        )
    )

    if manifest.get("status") != "frozen_not_evaluated":
        raise ValueError(
            "Final manifest is not frozen_not_evaluated."
        )

    return sorted({
        record["db_id"]
        for record in manifest["records"]
    })


def schema_exists(pg_cursor, schema_name):
    pg_cursor.execute(
        """
        SELECT 1
        FROM information_schema.schemata
        WHERE schema_name = %s
        """,
        (schema_name,),
    )
    return pg_cursor.fetchone() is not None


def validate_existing_database(db_id):

    sqlite_path = get_sqlite_database_path(db_id)

    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_cur = sqlite_conn.cursor()

    pg_conn = get_connection()
    pg_cur = pg_conn.cursor()

    try:
        sqlite_cur.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )

        sqlite_tables = [
            row[0]
            for row in sqlite_cur.fetchall()
        ]

        pg_cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """,
            (db_id,),
        )

        pg_tables = [
            row[0]
            for row in pg_cur.fetchall()
        ]

        if set(sqlite_tables) != set(pg_tables):
            raise RuntimeError(
                f"Existing PostgreSQL schema does not "
                f"match SQLite tables: {db_id}"
            )

        for table_name in sqlite_tables:
            escaped_table = table_name.replace(
                '"',
                '""',
            )

            sqlite_cur.execute(
                f'SELECT COUNT(*) '
                f'FROM "{escaped_table}"'
            )

            sqlite_count = (
                sqlite_cur.fetchone()[0]
            )

            pg_cur.execute(
                sql.SQL(
                    "SELECT COUNT(*) FROM {}.{}"
                ).format(
                    sql.Identifier(db_id),
                    sql.Identifier(table_name),
                )
            )

            pg_count = pg_cur.fetchone()[0]

            if sqlite_count != pg_count:
                raise RuntimeError(
                    f"Existing PostgreSQL row-count "
                    f"mismatch: {db_id}.{table_name} "
                    f"SQLite={sqlite_count} "
                    f"PostgreSQL={pg_count}"
                )

    finally:
        sqlite_cur.close()
        sqlite_conn.close()
        pg_cur.close()
        pg_conn.close()


def import_database(db_id):
    sqlite_path = get_sqlite_database_path(db_id)

    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_cur = sqlite_conn.cursor()

    pg_conn = get_connection()
    pg_cur = pg_conn.cursor()

    try:
        if schema_exists(pg_cur, db_id):
            raise RuntimeError(
                f"PostgreSQL schema already exists: {db_id}"
            )

        pg_cur.execute(
            sql.SQL("CREATE SCHEMA {}").format(
                sql.Identifier(db_id)
            )
        )

        sqlite_cur.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )

        tables = [
            row[0]
            for row in sqlite_cur.fetchall()
        ]

        for table_name in tables:
            escaped_table = table_name.replace(
                '"',
                '""',
            )

            sqlite_cur.execute(
                f'PRAGMA table_info("{escaped_table}")'
            )

            columns = sqlite_cur.fetchall()

            column_defs = []

            for column in columns:
                column_name = column[1]
                declared_type = column[2]

                pg_type = map_sqlite_type(
                    declared_type
                )

                declared_upper = (
                    declared_type or ""
                ).strip().upper()

                if (
                    declared_upper == "DATE"
                    or declared_upper.startswith(
                        "DATETIME"
                    )
                ):
                    escaped_column = (
                        column_name.replace(
                            '"',
                            '""',
                        )
                    )

                    sqlite_cur.execute(
                        f"""
                        SELECT DISTINCT
                            typeof("{escaped_column}")
                        FROM "{escaped_table}"
                        WHERE "{escaped_column}"
                            IS NOT NULL
                        """
                    )

                    storage_types = {
                        row[0]
                        for row
                        in sqlite_cur.fetchall()
                    }

                    if storage_types == {"integer"}:
                        pg_type = "INTEGER"

                    elif storage_types == {"real"}:
                        pg_type = (
                            "DOUBLE PRECISION"
                        )

                column_defs.append(
                    sql.SQL("{} {}").format(
                        sql.Identifier(column_name),
                        sql.SQL(pg_type),
                    )
                )

            create_table = sql.SQL(
                "CREATE TABLE {}.{} ({})"
            ).format(
                sql.Identifier(db_id),
                sql.Identifier(table_name),
                sql.SQL(", ").join(
                    column_defs
                ),
            )

            pg_cur.execute(create_table)

            sqlite_cur.execute(
                f'SELECT * FROM "{escaped_table}"'
            )

            rows = sqlite_cur.fetchall()

            if rows:
                placeholders = sql.SQL(", ").join(
                    sql.Placeholder()
                    for _ in columns
                )

                insert_stmt = sql.SQL(
                    "INSERT INTO {}.{} VALUES ({})"
                ).format(
                    sql.Identifier(db_id),
                    sql.Identifier(table_name),
                    placeholders,
                )

                pg_cur.executemany(
                    insert_stmt,
                    rows,
                )

        pg_conn.commit()

    except Exception:
        pg_conn.rollback()
        raise

    finally:
        sqlite_cur.close()
        sqlite_conn.close()

        pg_cur.close()
        pg_conn.close()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help=(
            "Skip PostgreSQL schemas that already "
            "exist instead of failing."
        ),
    )

    args = parser.parse_args()

    db_ids = get_final_database_ids()

    print(
        "===== FINAL TEST POSTGRES IMPORT ====="
    )
    print("Databases:", len(db_ids))

    pg_conn = get_connection()
    pg_cur = pg_conn.cursor()

    try:
        existing = {
            db_id
            for db_id in db_ids
            if schema_exists(pg_cur, db_id)
        }
    finally:
        pg_cur.close()
        pg_conn.close()

    if existing and not args.skip_existing:
        raise RuntimeError(
            "Final PostgreSQL schemas already exist: "
            + ", ".join(sorted(existing))
        )

    for index, db_id in enumerate(
        db_ids,
        start=1,
    ):
        print(
            f"[{index}/{len(db_ids)}] {db_id}"
        )

        if db_id in existing:
            validate_existing_database(db_id)
            print(
                "  ✅ existing schema validated; skipped"
            )
            continue

        import_database(db_id)

        print("  ✅ imported")

    print()
    print(
        "✅ Final database import/validation complete."
    )


if __name__ == "__main__":
    main()
