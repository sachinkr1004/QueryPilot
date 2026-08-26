import re


# ============================================================
# NORMALIZE TABLE IDENTIFIER
# ============================================================

def normalize_table_name(name):
    if not name:
        return None

    name = name.strip()

    # Remove trailing punctuation.
    name = name.rstrip(
        ",;"
    )

    # If schema-qualified, keep only table name.
    if "." in name:
        name = name.split(".")[-1]

    # Remove PostgreSQL/SQL quoting.
    name = (
        name
        .replace('"', "")
        .replace("`", "")
        .replace("[", "")
        .replace("]", "")
    )

    return name.lower().strip()


# ============================================================
# EXTRACT REQUIRED TABLES FROM GOLD SQL
# ============================================================

def extract_required_tables(sql):
    """
    Extract tables that occur after FROM or JOIN.

    This is used ONLY for post-prediction retrieval
    evaluation. Gold SQL is never exposed to generation.
    """

    if not sql:
        return set()

    pattern = re.compile(
        r"""
        \b(?:FROM|JOIN)\s+
        (
            (?:
                "?[A-Za-z_][A-Za-z0-9_]*"?
                \.
            )?
            "?[A-Za-z_][A-Za-z0-9_]*"?
        )
        """,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    tables = set()

    for match in pattern.finditer(sql):

        table_name = normalize_table_name(
            match.group(1)
        )

        if table_name:
            tables.add(
                table_name
            )

    return tables


# ============================================================
# REQUIRED-TABLE RECALL
# ============================================================

def required_table_recall(
    gold_sql,
    retrieved_tables,
):

    required = extract_required_tables(
        gold_sql
    )

    retrieved = {
        normalize_table_name(table)
        for table in retrieved_tables
    }

    retrieved.discard(None)

    if not required:
        return {
            "required_tables": [],
            "retrieved_required_tables": [],
            "missing_required_tables": [],
            "required_table_recall": 100.0,
        }

    found = (
        required
        & retrieved
    )

    missing = (
        required
        - retrieved
    )

    recall = (
        len(found)
        / len(required)
        * 100
    )

    return {
        "required_tables": sorted(
            required
        ),
        "retrieved_required_tables": sorted(
            found
        ),
        "missing_required_tables": sorted(
            missing
        ),
        "required_table_recall": round(
            recall,
            2,
        ),
    }
