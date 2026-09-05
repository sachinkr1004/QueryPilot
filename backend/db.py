import os
import re

import psycopg2
import sqlglot
from sqlglot import exp
from dotenv import load_dotenv


load_dotenv()


class UnsafeSQLError(ValueError):
    """Raised when SQL violates QueryPilot's read-only safety policy."""

    pass


def get_connection():

    return psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT")
    )


def is_safe_sql(sql: str) -> bool:
    """
    Validate that SQL is a single read-only PostgreSQL query expression.

    Safety rules:
    - SQL must parse successfully.
    - Exactly one statement is allowed.
    - The top-level statement must be a read-only query expression.
    - No data-changing or DDL statements may appear anywhere,
      including inside CTEs.
    - SELECT INTO is forbidden because it creates a table.
    - Row-locking clauses such as FOR UPDATE are forbidden.
    """

    if not sql or not sql.strip():
        return False

    try:
        statements = sqlglot.parse(
            sql,
            read="postgres"
        )
    except Exception:
        return False

    if len(statements) != 1:
        return False

    statement = statements[0]

    if not isinstance(statement, exp.Query):
        return False

    blocked_nodes = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Merge,
        exp.Drop,
        exp.Create,
        exp.Alter,
        exp.TruncateTable,
        exp.Grant,
        exp.Revoke,
    )

    for node_type in blocked_nodes:
        if next(
            statement.find_all(node_type),
            None
        ) is not None:
            return False

    if next(statement.find_all(exp.Into), None) is not None:
        return False

    if next(
        statement.find_all(exp.Lock),
        None
    ) is not None:
        return False

    return True


def get_table_metadata():
    """
    Load real PostgreSQL table names.

    Returns a dictionary like:

    {
        ("pets_1", "pets"): "Pets",
        ("pets_1", "student"): "Student",
        ("pets_1", "has_pet"): "Has_Pet"
    }

    The lowercase key helps us recognize an incorrectly
    unquoted identifier, while the value stores the real
    PostgreSQL table name.
    """

    conn = get_connection()
    cursor = None

    try:

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                table_schema,
                table_name
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE'
              AND table_schema NOT IN (
                  'pg_catalog',
                  'information_schema'
              );
            """
        )

        rows = cursor.fetchall()

        metadata = {}

        for schema_name, table_name in rows:

            metadata[
                (
                    schema_name.lower(),
                    table_name.lower()
                )
            ] = table_name

        return metadata

    finally:

        if cursor is not None:
            cursor.close()

        conn.close()


def repair_table_identifiers(sql: str) -> str:
    """
    Repair schema-qualified table references using actual
    PostgreSQL metadata.

    Example:

        pets_1.Pets

    becomes:

        pets_1."Pets"

    because PostgreSQL metadata says the actual table name
    is Pets.

    Lowercase tables such as:

        world_1.country

    remain unchanged.
    """

    metadata = get_table_metadata()

    pattern = re.compile(
        r"""
        \b(FROM|JOIN)\s+
        ("?[A-Za-z_][A-Za-z0-9_]*"?)
        \.
        ("?[A-Za-z_][A-Za-z0-9_]*"?)
        """,
        flags=re.IGNORECASE | re.VERBOSE
    )

    def replace_table(match):

        keyword = match.group(1)

        schema_token = match.group(2)
        table_token = match.group(3)

        schema_name = schema_token.strip('"')
        requested_table = table_token.strip('"')

        key = (
            schema_name.lower(),
            requested_table.lower()
        )

        actual_table = metadata.get(key)

        if actual_table is None:
            return match.group(0)

        # Preserve/repair PostgreSQL schema casing.
        #
        # Mixed-case schema names must remain quoted, otherwise
        # PostgreSQL folds them to lowercase.
        if schema_name == schema_name.lower():
            repaired_schema = schema_token
        else:
            repaired_schema = f'"{schema_name}"'

        # Lowercase PostgreSQL identifiers do not require quotes.
        if actual_table == actual_table.lower():

            repaired_table = actual_table

        else:

            repaired_table = (
                f'"{actual_table}"'
            )

        return (
            f"{keyword} "
            f"{repaired_schema}."
            f"{repaired_table}"
        )

    return pattern.sub(
        replace_table,
        sql
    )


def prepare_sql(sql: str) -> str:
    """
    General SQL preparation pipeline.

    1. Check read-only safety.
    2. Repair schema-qualified table identifiers using
       PostgreSQL metadata.
    3. Check safety again.
    """

    if not is_safe_sql(sql):

        raise UnsafeSQLError(
            "Unsafe SQL blocked. "
            "Only read-only SELECT queries are allowed."
        )

    repaired_sql = repair_table_identifiers(
        sql
    )

    if not is_safe_sql(repaired_sql):

        raise UnsafeSQLError(
            "Unsafe SQL blocked after SQL preparation."
        )

    return repaired_sql


def execute_query(sql: str):

    prepared_sql = prepare_sql(
        sql
    )

    conn = get_connection()

    cursor = None

    try:

        # Defense in depth: PostgreSQL itself enforces that
        # generated queries cannot modify database state.
        conn.set_session(readonly=True)

        cursor = conn.cursor()

        # Prevent generated queries from consuming database
        # resources indefinitely. SET LOCAL limits the timeout
        # to the current transaction only.
        cursor.execute(
            "SET LOCAL statement_timeout = '10s';"
        )

        cursor.execute(
            prepared_sql
        )

        rows = cursor.fetchall()

        return rows

    finally:

        if cursor is not None:
            cursor.close()

        conn.close()
