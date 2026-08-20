import os
import re

import psycopg2
from dotenv import load_dotenv


load_dotenv()


def get_connection():

    return psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT")
    )


def is_safe_sql(sql: str) -> bool:

    sql_clean = sql.strip().lower()

    if not (
        sql_clean.startswith("select")
        or sql_clean.startswith("with")
    ):
        return False

    blocked_keywords = [
        "insert ",
        "update ",
        "delete ",
        "drop ",
        "alter ",
        "truncate ",
        "create ",
        "grant ",
        "revoke "
    ]

    for keyword in blocked_keywords:
        if keyword in sql_clean:
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

        # Lowercase PostgreSQL identifiers do not require quotes.
        if actual_table == actual_table.lower():

            repaired_table = actual_table

        else:

            repaired_table = (
                f'"{actual_table}"'
            )

        return (
            f"{keyword} "
            f"{schema_name}."
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

        raise ValueError(
            "Unsafe SQL blocked. "
            "Only read-only SELECT queries are allowed."
        )

    repaired_sql = repair_table_identifiers(
        sql
    )

    if not is_safe_sql(repaired_sql):

        raise ValueError(
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

        cursor = conn.cursor()

        cursor.execute(
            prepared_sql
        )

        rows = cursor.fetchall()

        return rows

    finally:

        if cursor is not None:
            cursor.close()

        conn.close()
