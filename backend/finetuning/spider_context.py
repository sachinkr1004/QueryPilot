import json

from functools import lru_cache
from pathlib import Path


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

BACKEND_DIR = BASE_DIR.parent

PROJECT_ROOT = BACKEND_DIR.parent

SPIDER_ROOT = (
    PROJECT_ROOT
    / "dataset"
    / "spider"
    / "spider_data"
    / "spider_data"
)

TABLES_PATH = (
    SPIDER_ROOT
    / "tables.json"
)

DATABASE_ROOT = (
    SPIDER_ROOT
    / "database"
)


# ============================================================
# LOAD SPIDER SCHEMA METADATA
# ============================================================

@lru_cache(maxsize=1)
def load_spider_schema_map():
    """
    Load tables.json once and return:

        {
            db_id: schema_record
        }
    """

    with TABLES_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        records = json.load(file)

    return {
        record["db_id"]: record
        for record in records
    }


# ============================================================
# GET ONE DATABASE RECORD
# ============================================================

def get_spider_schema_record(
    database_name: str,
):
    """
    Return the raw Spider tables.json schema record.
    """

    schema_map = load_spider_schema_map()

    record = schema_map.get(
        database_name
    )

    if record is None:
        raise ValueError(
            "Spider schema not found for database: "
            f"{database_name}"
        )

    return record


# ============================================================
# BUILD STRUCTURED METADATA
# ============================================================

def build_database_metadata(
    database_name: str,
):
    """
    Build structured metadata for one Spider database.

    Returns:
        {
            "database_name": ...,
            "tables": {
                table_name: {
                    "columns": [...],
                    "column_types": {...},
                    "primary_keys": [...],
                }
            },
            "foreign_keys": [...]
        }
    """

    record = get_spider_schema_record(
        database_name
    )

    table_names = record[
        "table_names_original"
    ]

    column_names = record[
        "column_names_original"
    ]

    column_types = record[
        "column_types"
    ]

    primary_keys = set(
        record["primary_keys"]
    )

    foreign_keys = record[
        "foreign_keys"
    ]


    tables = {}

    for table_name in table_names:
        tables[table_name] = {
            "columns": [],
            "column_types": {},
            "primary_keys": [],
        }


    # --------------------------------------------------------
    # Columns
    # --------------------------------------------------------

    for column_index, (
        table_index,
        column_name,
    ) in enumerate(column_names):

        # Spider uses table_index = -1 for "*".
        if table_index == -1:
            continue

        table_name = table_names[
            table_index
        ]

        tables[
            table_name
        ][
            "columns"
        ].append(
            column_name
        )

        tables[
            table_name
        ][
            "column_types"
        ][
            column_name
        ] = column_types[
            column_index
        ]

        if column_index in primary_keys:

            tables[
                table_name
            ][
                "primary_keys"
            ].append(
                column_name
            )


    # --------------------------------------------------------
    # Foreign-key relationships
    # --------------------------------------------------------

    relationships = []

    for (
        source_column_index,
        target_column_index,
    ) in foreign_keys:

        source_table_index, source_column = (
            column_names[
                source_column_index
            ]
        )

        target_table_index, target_column = (
            column_names[
                target_column_index
            ]
        )

        source_table = table_names[
            source_table_index
        ]

        target_table = table_names[
            target_table_index
        ]

        relationships.append(
            {
                "source_table": source_table,
                "source_column": source_column,
                "target_table": target_table,
                "target_column": target_column,
            }
        )


    return {
        "database_name": database_name,
        "tables": tables,
        "foreign_keys": relationships,
    }


# ============================================================
# BUILD HUMAN-READABLE SCHEMA CONTEXT
# ============================================================

def build_schema_context(
    database_name: str,
):
    """
    Convert structured Spider metadata into model-readable
    schema context.
    """

    metadata = build_database_metadata(
        database_name
    )

    lines = [
        f"Database: {database_name}",
        "",
    ]


    for table_name, table_info in (
        metadata["tables"].items()
    ):

        lines.append(
            f"Table: {table_name}"
        )

        lines.append(
            "Columns:"
        )

        for column_name in (
            table_info["columns"]
        ):

            column_type = (
                table_info[
                    "column_types"
                ][
                    column_name
                ]
            )

            suffix = ""

            if column_name in (
                table_info[
                    "primary_keys"
                ]
            ):
                suffix = " [PRIMARY KEY]"

            lines.append(
                f"- {column_name}: "
                f"{column_type}"
                f"{suffix}"
            )

        lines.append("")


    lines.append(
        "Relationships:"
    )

    if metadata["foreign_keys"]:

        for relationship in (
            metadata["foreign_keys"]
        ):

            lines.append(
                "- "
                f"{relationship['source_table']}."
                f"{relationship['source_column']}"
                " -> "
                f"{relationship['target_table']}."
                f"{relationship['target_column']}"
            )

    else:
        lines.append(
            "- None"
        )


    return "\n".join(
        lines
    ).strip()


# ============================================================
# SQLITE DATABASE PATH
# ============================================================

def get_sqlite_database_path(
    database_name: str,
):
    """
    Return the SQLite database path for one Spider DB.
    """

    path = (
        DATABASE_ROOT
        / database_name
        / f"{database_name}.sqlite"
    )

    if not path.exists():
        raise FileNotFoundError(
            "SQLite database not found: "
            f"{path}"
        )

    return path


# ============================================================
# MANUAL TEST
# ============================================================

if __name__ == "__main__":

    database_name = "allergy_1"

    metadata = build_database_metadata(
        database_name
    )

    print("=" * 80)
    print("PHASE 7.2H.2 - SPIDER CONTEXT UTILITY")
    print("=" * 80)

    print()
    print(
        "Database:",
        metadata["database_name"],
    )

    print(
        "Tables:",
        len(metadata["tables"]),
    )

    print(
        "Foreign keys:",
        len(metadata["foreign_keys"]),
    )

    print()
    print("SCHEMA CONTEXT:")
    print()

    print(
        build_schema_context(
            database_name
        )
    )

    print()
    print(
        "SQLite path:",
        get_sqlite_database_path(
            database_name
        ),
    )

    print()
    print("=" * 80)
    print(
        "✅ SPIDER CONTEXT UTILITY READY"
    )
    print("=" * 80)
