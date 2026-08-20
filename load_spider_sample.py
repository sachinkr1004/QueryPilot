import os
import sqlite3

import psycopg2
from dotenv import load_dotenv


load_dotenv("backend/.env")


# ============================================================
# CONFIGURATION
# ============================================================

DB_NAMES = [
    "concert_singer",
    "pets_1",
    "car_1",
    "employee_hire_evaluation",
    "world_1",
]


SPIDER_DB_FOLDER = (
    "dataset/spider/spider_data/spider_data/database"
)


PG_CONN = {
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", "5432")),
}


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def quote_identifier(name):
    """
    Safely quote PostgreSQL/SQLite identifiers.
    """

    return '"' + name.replace('"', '""') + '"'


def sqlite_type_to_postgres(sqlite_type: str) -> str:
    """
    Convert common SQLite column types into PostgreSQL types.
    """

    column_type = (sqlite_type or "").upper()

    if "INT" in column_type:
        return "INTEGER"

    if any(
        value in column_type
        for value in ["REAL", "FLOA", "DOUB"]
    ):
        return "DOUBLE PRECISION"

    if any(
        value in column_type
        for value in ["NUMERIC", "DECIMAL"]
    ):
        return "NUMERIC"

    if "BLOB" in column_type:
        return "BYTEA"

    return "TEXT"


def get_table_info(cursor, table_name):
    """
    Return SQLite PRAGMA table information.
    """

    cursor.execute(
        f'PRAGMA table_info({quote_identifier(table_name)})'
    )

    return cursor.fetchall()


def get_sqlite_column_type(
    cursor,
    table_name,
    column_name,
):
    """
    Find the declared SQLite type of a column.
    """

    columns = get_table_info(
        cursor,
        table_name,
    )

    for column in columns:

        if column[1] == column_name:
            return column[2]

    return None


def get_foreign_keys(
    cursor,
    table_name,
):
    """
    Return SQLite foreign-key metadata.
    """

    cursor.execute(
        f'PRAGMA foreign_key_list('
        f'{quote_identifier(table_name)})'
    )

    return cursor.fetchall()


def get_foreign_key_type_overrides(
    cursor,
    table_name,
):
    """
    Make FK column types compatible with the referenced column.

    This is important because some Spider databases declare
    related columns using slightly different SQLite types.
    PostgreSQL is stricter about type compatibility.
    """

    overrides = {}

    foreign_keys = get_foreign_keys(
        cursor,
        table_name,
    )

    for fk in foreign_keys:

        referenced_table = fk[2]
        local_column = fk[3]
        referenced_column = fk[4]

        referenced_type = get_sqlite_column_type(
            cursor,
            referenced_table,
            referenced_column,
        )

        if referenced_type:

            overrides[
                local_column
            ] = referenced_type

    return overrides


def get_primary_key_columns(columns):
    """
    Return primary-key columns in the correct PK order.

    SQLite PRAGMA table_info returns the PK position
    in column[5].
    """

    pk_columns = [
        (column[5], column[1])
        for column in columns
        if column[5] > 0
    ]

    pk_columns.sort(
        key=lambda item: item[0]
    )

    return [
        column_name
        for _, column_name in pk_columns
    ]


# ============================================================
# CREATE TABLES
# ============================================================

def create_tables(
    sqlite_cursor,
    postgres_cursor,
    db_name,
    tables,
):
    """
    Create PostgreSQL tables using SQLite schema metadata.
    """

    for table_name in tables:

        print(
            f"  → Creating table: {table_name}"
        )

        columns = get_table_info(
            sqlite_cursor,
            table_name,
        )

        fk_type_overrides = (
            get_foreign_key_type_overrides(
                sqlite_cursor,
                table_name,
            )
        )

        col_defs_list = []

        for column in columns:

            column_name = column[1]
            declared_type = column[2]

            effective_type = (
                fk_type_overrides.get(
                    column_name,
                    declared_type,
                )
            )

            pg_type = sqlite_type_to_postgres(
                effective_type
            )

            col_defs_list.append(
                f'{quote_identifier(column_name)} '
                f'{pg_type}'
            )

        # ----------------------------------------------------
        # PRIMARY KEY
        # ----------------------------------------------------

        primary_key_columns = (
            get_primary_key_columns(
                columns
            )
        )

        if primary_key_columns:

            quoted_pk_columns = ", ".join(
                quote_identifier(column)
                for column
                in primary_key_columns
            )

            col_defs_list.append(
                f"PRIMARY KEY "
                f"({quoted_pk_columns})"
            )

        col_defs = ", ".join(
            col_defs_list
        )

        postgres_cursor.execute(
            f'CREATE TABLE '
            f'{quote_identifier(db_name)}.'
            f'{quote_identifier(table_name)} '
            f'({col_defs});'
        )


# ============================================================
# LOAD DATA
# ============================================================

def load_rows(
    sqlite_cursor,
    postgres_cursor,
    db_name,
    tables,
):
    """
    Copy all rows from SQLite into PostgreSQL.
    """

    for table_name in tables:

        print(
            f"  → Loading table: {table_name}"
        )

        columns = get_table_info(
            sqlite_cursor,
            table_name,
        )

        col_names = [
            column[1]
            for column in columns
        ]

        sqlite_cursor.execute(
            f'SELECT * FROM '
            f'{quote_identifier(table_name)}'
        )

        rows = sqlite_cursor.fetchall()

        if rows:

            placeholders = ", ".join(
                ["%s"] * len(col_names)
            )

            quoted_columns = ", ".join(
                quote_identifier(name)
                for name in col_names
            )

            postgres_cursor.executemany(
                f'INSERT INTO '
                f'{quote_identifier(db_name)}.'
                f'{quote_identifier(table_name)} '
                f'({quoted_columns}) '
                f'VALUES ({placeholders})',
                rows,
            )

        print(
            f"     ✅ {len(rows)} rows loaded"
        )


# ============================================================
# CREATE FOREIGN KEYS
# ============================================================

def create_foreign_keys(
    sqlite_cursor,
    postgres_cursor,
    db_name,
    tables,
):
    """
    Read Spider SQLite foreign-key relationships and attempt
    to create equivalent PostgreSQL FK constraints.

    SAVEPOINT is used so that one invalid FK does not roll back
    previously created FK constraints.
    """

    print()
    print("  🔗 Creating foreign keys...")

    relationship_count = 0
    skipped_count = 0
    attempt_count = 0

    for table_name in tables:

        foreign_keys = get_foreign_keys(
            sqlite_cursor,
            table_name,
        )

        for index, fk in enumerate(
            foreign_keys,
            start=1,
        ):

            attempt_count += 1

            referenced_table = fk[2]
            local_column = fk[3]
            referenced_column = fk[4]

            constraint_name = (
                f"fk_{table_name}_{index}"
            )

            savepoint_name = (
                f"fk_savepoint_{attempt_count}"
            )

            # ------------------------------------------------
            # SAVEPOINT
            # ------------------------------------------------

            postgres_cursor.execute(
                f"SAVEPOINT {savepoint_name};"
            )

            try:

                postgres_cursor.execute(
                    f'ALTER TABLE '
                    f'{quote_identifier(db_name)}.'
                    f'{quote_identifier(table_name)} '
                    f'ADD CONSTRAINT '
                    f'{quote_identifier(constraint_name)} '
                    f'FOREIGN KEY '
                    f'({quote_identifier(local_column)}) '
                    f'REFERENCES '
                    f'{quote_identifier(db_name)}.'
                    f'{quote_identifier(referenced_table)} '
                    f'({quote_identifier(referenced_column)});'
                )

                postgres_cursor.execute(
                    f"RELEASE SAVEPOINT "
                    f"{savepoint_name};"
                )

                relationship_count += 1

                print(
                    f"     ✅ "
                    f"{table_name}."
                    f"{local_column}"
                    f" → "
                    f"{referenced_table}."
                    f"{referenced_column}"
                )

            except psycopg2.Error as error:

                # Roll back ONLY this FK attempt.
                postgres_cursor.execute(
                    f"ROLLBACK TO SAVEPOINT "
                    f"{savepoint_name};"
                )

                postgres_cursor.execute(
                    f"RELEASE SAVEPOINT "
                    f"{savepoint_name};"
                )

                skipped_count += 1

                error_message = (
                    error.pgerror.strip()
                    if error.pgerror
                    else str(error)
                )

                print(
                    f"     ⚠️ Could not enforce "
                    f"{table_name}."
                    f"{local_column}"
                    f" → "
                    f"{referenced_table}."
                    f"{referenced_column}"
                )

                print(
                    f"        PostgreSQL: "
                    f"{error_message}"
                )

    print()

    print(
        f"  🔗 {relationship_count} "
        f"foreign-key constraints created"
    )

    print(
        f"  ⚠️ {skipped_count} "
        f"relationships could not be enforced"
    )


# ============================================================
# MAIN IMPORT PROCESS
# ============================================================

def main():
    for db_name in DB_NAMES:

        sqlite_path = os.path.join(
            SPIDER_DB_FOLDER,
            db_name,
            f"{db_name}.sqlite",
        )

        # --------------------------------------------------------
        # CHECK SQLITE DATABASE EXISTS
        # --------------------------------------------------------

        if not os.path.exists(
            sqlite_path
        ):

            print(
                f"❌ {db_name} NOT FOUND"
            )

            print(
                f"   Expected: {sqlite_path}"
            )

            continue

        print()

        print(
            "=" * 70
        )

        print(
            f"===== Loading {db_name} ====="
        )

        print(
            "=" * 70
        )

        # --------------------------------------------------------
        # CONNECT TO SQLITE
        # --------------------------------------------------------

        sconn = sqlite3.connect(
            sqlite_path
        )

        scur = sconn.cursor()

        # --------------------------------------------------------
        # CONNECT TO POSTGRESQL
        # --------------------------------------------------------

        pconn = psycopg2.connect(
            **PG_CONN
        )

        pcur = pconn.cursor()

        try:

            # ----------------------------------------------------
            # RESET DATABASE SCHEMA
            # ----------------------------------------------------

            pcur.execute(
                f'DROP SCHEMA IF EXISTS '
                f'{quote_identifier(db_name)} '
                f'CASCADE;'
            )

            pcur.execute(
                f'CREATE SCHEMA '
                f'{quote_identifier(db_name)};'
            )

            # ----------------------------------------------------
            # FIND SQLITE TABLES
            # ----------------------------------------------------

            scur.execute(
                "SELECT name "
                "FROM sqlite_master "
                "WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%';"
            )

            tables = [
                row[0]
                for row in scur.fetchall()
            ]

            print(
                f"Found {len(tables)} tables"
            )

            # ----------------------------------------------------
            # CREATE POSTGRES TABLES
            # ----------------------------------------------------

            print()
            print(
                "📦 Creating tables..."
            )

            create_tables(
                scur,
                pcur,
                db_name,
                tables,
            )

            # ----------------------------------------------------
            # COPY DATA
            # ----------------------------------------------------

            print()
            print(
                "📥 Loading data..."
            )

            load_rows(
                scur,
                pcur,
                db_name,
                tables,
            )

            # Commit tables + data before FK creation.
            pconn.commit()

            # ----------------------------------------------------
            # CREATE FK RELATIONSHIPS
            # ----------------------------------------------------

            create_foreign_keys(
                scur,
                pcur,
                db_name,
                tables,
            )

            pconn.commit()

            print()

            print(
                f"===== Finished "
                f"{db_name} ====="
            )

        except Exception:

            pconn.rollback()

            raise

        finally:

            pcur.close()
            pconn.close()

            scur.close()
            sconn.close()


    print()

    print(
        "🎉 ALL 5 DATABASES LOADED SUCCESSFULLY!"
    )


if __name__ == "__main__":
    main()
