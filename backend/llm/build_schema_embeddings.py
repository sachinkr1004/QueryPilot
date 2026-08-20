import os
import sqlite3

from sentence_transformers import SentenceTransformer

from db import get_connection


SCHEMAS = [
    "car_1",
    "concert_singer",
    "employee_hire_evaluation",
    "pets_1",
    "world_1",
]


SPIDER_DB_FOLDER = (
    "../dataset/spider/"
    "spider_data/spider_data/database"
)



def get_sqlite_path(schema_name):
    return os.path.join(
        SPIDER_DB_FOLDER,
        schema_name,
        f"{schema_name}.sqlite",
    )


def get_relationships(schema_name):
    """
    Read foreign-key relationships directly from the
    original Spider SQLite database.

    We use SQLite metadata instead of PostgreSQL FK
    constraints because some Spider relationships cannot
    be physically enforced by PostgreSQL even though they
    are useful schema information for SQL generation.
    """

    sqlite_path = get_sqlite_path(schema_name)

    if not os.path.exists(sqlite_path):
        raise FileNotFoundError(
            f"Spider database not found: {sqlite_path}"
        )

    conn = sqlite3.connect(sqlite_path)
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name;
            """
        )

        tables = [
            row[0]
            for row in cursor.fetchall()
        ]

        relationships = []

        for table_name in tables:

            cursor.execute(
                f'PRAGMA foreign_key_list("{table_name}")'
            )

            foreign_keys = cursor.fetchall()

            for fk in foreign_keys:

                referenced_table = fk[2]
                local_column = fk[3]
                referenced_column = fk[4]

                relationships.append(
                    (
                        table_name,
                        local_column,
                        referenced_table,
                        referenced_column,
                    )
                )

        return relationships

    finally:
        cursor.close()
        conn.close()


def build_schema_text(cursor, schema_name):
    """
    Build rich schema text containing:

    1. Tables
    2. Column names
    3. PostgreSQL data types
    4. Primary keys
    5. Spider foreign-key relationships
    """

    # --------------------------------------------------------
    # TABLES + COLUMNS + TYPES
    # --------------------------------------------------------

    cursor.execute(
        """
        SELECT
            table_name,
            column_name,
            data_type
        FROM information_schema.columns
        WHERE table_schema = %s
        ORDER BY table_name, ordinal_position;
        """,
        (schema_name,),
    )

    rows = cursor.fetchall()

    tables = {}

    for table_name, column_name, data_type in rows:

        if table_name not in tables:
            tables[table_name] = []

        tables[table_name].append(
            (column_name, data_type)
        )

    # --------------------------------------------------------
    # PRIMARY KEYS
    # --------------------------------------------------------

    cursor.execute(
        """
        SELECT
            tc.table_name,
            kcu.column_name,
            kcu.ordinal_position
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.constraint_schema = kcu.constraint_schema
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema = %s
        ORDER BY
            tc.table_name,
            kcu.ordinal_position;
        """,
        (schema_name,),
    )

    primary_keys = {}

    for table_name, column_name, _ in cursor.fetchall():

        if table_name not in primary_keys:
            primary_keys[table_name] = []

        primary_keys[table_name].append(
            column_name
        )

    # --------------------------------------------------------
    # BUILD TABLE DESCRIPTIONS
    # --------------------------------------------------------

    parts = [
        f"Database: {schema_name}"
    ]

    for table_name, columns in tables.items():

        column_lines = []

        pk_columns = set(
            primary_keys.get(table_name, [])
        )

        for column_name, data_type in columns:

            marker = ""

            if column_name in pk_columns:
                marker = " [PRIMARY KEY]"

            column_lines.append(
                f"- {column_name}: "
                f"{data_type}{marker}"
            )

        table_text = (
            f"Table: {schema_name}.{table_name}\n"
            f"Columns:\n"
            + "\n".join(column_lines)
        )

        parts.append(table_text)

    # --------------------------------------------------------
    # SPIDER RELATIONSHIPS
    # --------------------------------------------------------

    relationships = get_relationships(
        schema_name
    )

    if relationships:

        relationship_lines = [
            "Relationships:"
        ]

        for (
            table_name,
            local_column,
            referenced_table,
            referenced_column,
        ) in relationships:

            relationship_lines.append(
                f"- {schema_name}.{table_name}."
                f"{local_column} -> "
                f"{schema_name}.{referenced_table}."
                f"{referenced_column}"
            )

        parts.append(
            "\n".join(relationship_lines)
        )

    return "\n\n".join(parts)


def main():

    print("Loading embedding model...")

    model = SentenceTransformer(
        "all-MiniLM-L6-v2"
    )

    conn = get_connection()
    cursor = conn.cursor()

    try:

        for schema_name in SCHEMAS:

            print()
            print("=" * 70)
            print(
                f"Building schema for: {schema_name}"
            )
            print("=" * 70)

            schema_text = build_schema_text(
                cursor,
                schema_name,
            )

            if not schema_text:

                print(
                    f"No tables found for "
                    f"{schema_name}, skipping."
                )

                continue

            print()
            print(schema_text)
            print()

            embedding = model.encode(
                schema_text
            ).tolist()

            cursor.execute(
                """
                DELETE FROM schema_embeddings
                WHERE database_name = %s;
                """,
                (schema_name,),
            )

            cursor.execute(
                """
                INSERT INTO schema_embeddings
                    (
                        database_name,
                        schema_text,
                        embedding
                    )
                VALUES
                    (%s, %s, %s);
                """,
                (
                    schema_name,
                    schema_text,
                    embedding,
                ),
            )

            print(
                f"Stored embedding for: "
                f"{schema_name}"
            )

            print(
                f"Schema length: "
                f"{len(schema_text)}"
            )

            print(
                f"Vector size: "
                f"{len(embedding)}"
            )

        conn.commit()

        print()
        print(
            "All schema embeddings "
            "created successfully."
        )

    except Exception:

        conn.rollback()
        raise

    finally:

        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
