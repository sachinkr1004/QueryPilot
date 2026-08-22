"""
QueryPilot Phase 7.1D

Convert Spider SQLite-style gold SQL into PostgreSQL SQL
compatible with QueryPilot's production database schemas.

Conversion is AST-based using SQLGlot.
"""

from functools import lru_cache

from db import get_connection


# ============================================================
# TARGET DATABASES
# ============================================================

TARGET_DATABASES = {
    "concert_singer",
    "pets_1",
    "car_1",
    "employee_hire_evaluation",
    "world_1",
}


# ============================================================
# POSTGRESQL IDENTIFIER METADATA
# ============================================================

@lru_cache(maxsize=1)
def get_identifier_metadata():
    """
    Load the real PostgreSQL table and column names.

    Lookup is case-insensitive, while returned names preserve
    the exact PostgreSQL capitalization.

    Example:

        metadata["pets_1"]["pets"]

    returns information containing:

        actual_table = "Pets"

        columns["pettype"] = "PetType"
    """

    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT
                table_schema,
                table_name,
                column_name,
                data_type
            FROM information_schema.columns
            WHERE table_schema IN %s
            ORDER BY
                table_schema,
                table_name,
                ordinal_position;
            """,
            (tuple(TARGET_DATABASES),),
        )

        rows = cursor.fetchall()

        metadata = {}

        for (
            schema_name,
            table_name,
            column_name,
            data_type,
        ) in rows:

            database = metadata.setdefault(
                schema_name,
                {},
            )

            table = database.setdefault(
                table_name.lower(),
                {
                    "actual_table": table_name,
                    "columns": {},
                    "column_types": {},
                },
            )

            table["columns"][
                column_name.lower()
            ] = column_name

            table["column_types"][
                column_name.lower()
            ] = data_type

        return metadata

    finally:
        cursor.close()
        conn.close()


# ============================================================
# TABLE IDENTIFIER CONVERSION
# ============================================================

def convert_table_identifiers(
    tree,
    database_name: str,
):
    """
    Convert Spider table references into production
    PostgreSQL table references.

    Examples:

        singer
            ->
        concert_singer.singer

        Pets
            ->
        pets_1."Pets"

    Existing table aliases are preserved.
    """

    from sqlglot import exp

    metadata = get_identifier_metadata()

    if database_name not in metadata:
        raise ValueError(
            "Unknown database: "
            f"{database_name}"
        )

    database_metadata = metadata[
        database_name
    ]

    for table in tree.find_all(exp.Table):

        requested_table = table.name

        table_info = database_metadata.get(
            requested_table.lower()
        )

        if table_info is None:
            raise ValueError(
                "Unknown table "
                f"{requested_table!r} "
                "for database "
                f"{database_name!r}"
            )

        actual_table = table_info[
            "actual_table"
        ]

        # PostgreSQL folds unquoted identifiers to lowercase.
        # Quote only when the real table name is not lowercase.
        quote_table = (
            actual_table
            != actual_table.lower()
        )

        table.set(
            "this",
            exp.to_identifier(
                actual_table,
                quoted=quote_table,
            ),
        )

        table.set(
            "db",
            exp.to_identifier(
                database_name,
                quoted=False,
            ),
        )

    return tree



# ============================================================
# COLUMN + SQLITE STRING CONVERSION
# ============================================================

def convert_column_identifiers(
    tree,
    database_name: str,
):
    """
    Convert Spider/SQLite column identifiers into exact
    PostgreSQL identifiers.

    Also converts SQLite-style double-quoted text values such
    as "Republic" into PostgreSQL string literals 'Republic'
    when the quoted token is not a real column in the current
    SQL scope.
    """

    from sqlglot import exp
    from sqlglot.optimizer.scope import traverse_scope

    metadata = get_identifier_metadata()

    if database_name not in metadata:
        raise ValueError(
            "Unknown database: "
            f"{database_name}"
        )

    database_metadata = metadata[
        database_name
    ]

    # Process inner scopes before outer scopes.
    scopes = list(
        traverse_scope(tree)
    )

    for scope in scopes:

        # ----------------------------------------------------
        # Build source/alias -> table metadata for THIS scope
        # ----------------------------------------------------

        source_tables = {}

        for source_name, source in scope.sources.items():

            if not isinstance(
                source,
                exp.Table,
            ):
                continue

            requested_table = (
                source.name.lower()
            )

            table_info = database_metadata.get(
                requested_table
            )

            if table_info is None:
                continue

            source_tables[
                source_name.lower()
            ] = table_info

        # ----------------------------------------------------
        # Only handle columns whose nearest SELECT scope is
        # this exact scope.
        # ----------------------------------------------------

        for column in list(
            scope.expression.find_all(
                exp.Column
            )
        ):

            # Skip columns belonging to a nested SELECT.
            nearest_select = column.find_ancestor(
                exp.Select
            )

            if nearest_select is not scope.expression:
                continue

            column_name = column.name

            quoted = bool(
                column.this.args.get(
                    "quoted"
                )
            )

            # ------------------------------------------------
            # Qualified column, e.g. T2.name
            # ------------------------------------------------

            if column.table:

                source_name = (
                    column.table.lower()
                )

                table_info = source_tables.get(
                    source_name
                )

                if table_info is None:
                    raise ValueError(
                        "Could not resolve qualified column "
                        f"{column.sql()!r} "
                        f"in database {database_name!r}"
                    )

                actual_column = (
                    table_info["columns"].get(
                        column_name.lower()
                    )
                )

                if actual_column is None:
                    raise ValueError(
                        "Column not found: "
                        f"{column.sql()!r} "
                        f"in database {database_name!r}"
                    )

                column.set(
                    "this",
                    exp.to_identifier(
                        actual_column,
                        quoted=True,
                    ),
                )

                continue

            # ------------------------------------------------
            # Unqualified column
            # ------------------------------------------------

            matching_columns = []

            for table_info in (
                source_tables.values()
            ):

                actual_column = (
                    table_info["columns"].get(
                        column_name.lower()
                    )
                )

                if actual_column is not None:
                    matching_columns.append(
                        actual_column
                    )

            matching_columns = list(
                dict.fromkeys(
                    matching_columns
                )
            )

            # Exactly one valid PostgreSQL column.
            if len(matching_columns) == 1:

                actual_column = (
                    matching_columns[0]
                )

                column.set(
                    "this",
                    exp.to_identifier(
                        actual_column,
                        quoted=True,
                    ),
                )

                continue

            # No matching column + originally quoted:
            # SQLite often uses "text" as a string literal.
            if (
                len(matching_columns) == 0
                and quoted
            ):
                column.replace(
                    exp.Literal.string(
                        column_name
                    )
                )
                continue

            if len(matching_columns) == 0:
                raise ValueError(
                    "Could not resolve unqualified column "
                    f"{column.sql()!r} "
                    f"in database {database_name!r}"
                )

            raise ValueError(
                "Ambiguous unqualified column "
                f"{column.sql()!r} "
                f"in database {database_name!r}"
            )

    return tree


# ============================================================
# POSTGRESQL TYPE COMPATIBILITY
# ============================================================

def apply_postgres_type_compatibility(
    tree,
    database_name: str,
):
    """
    Repair SQLite -> PostgreSQL type differences when the
    original SQL explicitly uses numeric semantics on a
    PostgreSQL TEXT column.

    Examples:

        "Year" = 2014
            ->
        CAST("Year" AS DOUBLE PRECISION) = 2014

        AVG("Horsepower")
            ->
        AVG(CAST("Horsepower" AS DOUBLE PRECISION))
    """

    from sqlglot import exp
    from sqlglot.optimizer.scope import traverse_scope

    metadata = get_identifier_metadata()

    database_metadata = metadata[
        database_name
    ]

    def resolve_column_type(
        column,
        scope,
    ):
        """
        Resolve the PostgreSQL type of a column in the
        current SQL scope.
        """

        source_tables = {}

        for source_name, source in scope.sources.items():

            if not isinstance(
                source,
                exp.Table,
            ):
                continue

            table_info = database_metadata.get(
                source.name.lower()
            )

            if table_info is None:
                continue

            source_tables[
                source_name.lower()
            ] = table_info

        # Qualified column.
        if column.table:

            table_info = source_tables.get(
                column.table.lower()
            )

            if table_info is None:
                return None

            return table_info[
                "column_types"
            ].get(
                column.name.lower()
            )

        # Unqualified column.
        matches = []

        for table_info in source_tables.values():

            column_type = table_info[
                "column_types"
            ].get(
                column.name.lower()
            )

            if column_type is not None:
                matches.append(
                    column_type
                )

        matches = list(
            dict.fromkeys(matches)
        )

        if len(matches) == 1:
            return matches[0]

        return None


    def numeric_cast(column):
        """
        Build a safe PostgreSQL numeric conversion.

        Spider source data can contain the literal text
        value 'null' inside otherwise numeric TEXT columns.

        Example:

            Horsepower = '150', '220', 'null'

        Convert using:

            CAST(NULLIF(column, 'null') AS DOUBLE PRECISION)

        so the text value 'null' becomes SQL NULL before
        numeric conversion.
        """

        safe_value = exp.Nullif(
            this=column.copy(),
            expression=exp.Literal.string(
                "null"
            ),
        )

        return exp.Cast(
            this=safe_value,
            to=exp.DataType.build(
                "DOUBLE PRECISION"
            ),
        )


    for scope in traverse_scope(tree):

        # ----------------------------------------------------
        # Numeric aggregates over TEXT columns
        # ----------------------------------------------------

        for avg_node in list(
            scope.expression.find_all(
                exp.Avg
            )
        ):

            column = avg_node.this

            if not isinstance(
                column,
                exp.Column,
            ):
                continue

            nearest_select = column.find_ancestor(
                exp.Select
            )

            if nearest_select is not scope.expression:
                continue

            column_type = resolve_column_type(
                column,
                scope,
            )

            if column_type == "text":

                avg_node.set(
                    "this",
                    numeric_cast(
                        column
                    ),
                )


        # ----------------------------------------------------
        # Numeric comparisons involving TEXT columns
        # ----------------------------------------------------

        comparison_types = (
            exp.EQ,
            exp.NEQ,
            exp.GT,
            exp.GTE,
            exp.LT,
            exp.LTE,
        )

        for comparison in list(
            scope.expression.find_all(
                comparison_types
            )
        ):

            nearest_select = comparison.find_ancestor(
                exp.Select
            )

            if nearest_select is not scope.expression:
                continue

            left = comparison.this
            right = comparison.expression

            # Column <op> numeric literal
            if (
                isinstance(left, exp.Column)
                and isinstance(right, exp.Literal)
                and not right.is_string
            ):

                column_type = resolve_column_type(
                    left,
                    scope,
                )

                if column_type == "text":

                    comparison.set(
                        "this",
                        numeric_cast(
                            left
                        ),
                    )

            # numeric literal <op> Column
            elif (
                isinstance(right, exp.Column)
                and isinstance(left, exp.Literal)
                and not left.is_string
            ):

                column_type = resolve_column_type(
                    right,
                    scope,
                )

                if column_type == "text":

                    comparison.set(
                        "expression",
                        numeric_cast(
                            right
                        ),
                    )

    return tree



# ============================================================
# SQLITE BARE-COLUMN MIN/MAX COMPATIBILITY
# ============================================================

def apply_sqlite_bare_extreme_compatibility(
    tree,
):
    """
    Rewrite SQLite bare-column MIN/MAX semantics into
    PostgreSQL-compatible SQL.

    SQLite permits queries such as:

        SELECT Language, CountryCode, MAX(Percentage)
        FROM countrylanguage
        GROUP BY CountryCode

    where the bare Language value comes from a row associated
    with the maximum Percentage.

    PostgreSQL does not permit this syntax.

    For grouped single-table MAX/MIN queries, rewrite using
    PostgreSQL DISTINCT ON.

    For an ungrouped query with one MAX/MIN aggregate and
    bare columns, rewrite it as ORDER BY extreme-column
    + LIMIT 1.
    """

    from sqlglot import exp

    for select in list(
        tree.find_all(exp.Select)
    ):

        projections = list(
            select.expressions
        )

        extreme_nodes = []

        bare_columns = []

        for projection in projections:

            expression = (
                projection.this
                if isinstance(
                    projection,
                    exp.Alias,
                )
                else projection
            )

            if isinstance(
                expression,
                (exp.Max, exp.Min),
            ):
                if isinstance(
                    expression.this,
                    exp.Column,
                ):
                    extreme_nodes.append(
                        expression
                    )

            elif isinstance(
                expression,
                exp.Column,
            ):
                bare_columns.append(
                    expression
                )

        # Only handle the precise SQLite bare-column
        # MIN/MAX pattern.
        #
        # There must be exactly ONE aggregate function in
        # the SELECT, and that aggregate must be MIN or MAX.
        #
        # Example that SHOULD be rewritten:
        #
        #   SELECT Language, CountryCode, MAX(Percentage)
        #   FROM countrylanguage
        #   GROUP BY CountryCode
        #
        # Example that must NOT be rewritten:
        #
        #   SELECT AVG(pet_age), MAX(pet_age), PetType
        #   FROM Pets
        #   GROUP BY PetType
        #
        # because AVG + MAX is normal aggregate SQL and is
        # already valid PostgreSQL.
        aggregate_nodes = []

        for projection in projections:

            aggregate_nodes.extend(
                list(
                    projection.find_all(
                        exp.AggFunc
                    )
                )
            )

        if (
            len(extreme_nodes) != 1
            or len(aggregate_nodes) != 1
            or not bare_columns
        ):
            continue

        extreme = extreme_nodes[0]
        extreme_column = extreme.this.copy()

        is_max = isinstance(
            extreme,
            exp.Max,
        )

        group = select.args.get(
            "group"
        )

        # ----------------------------------------------------
        # GROUPED case:
        #
        # SELECT Language, CountryCode, MAX(Percentage)
        # FROM ...
        # GROUP BY CountryCode
        #
        # ->
        #
        # SELECT DISTINCT ON (CountryCode)
        #        Language, CountryCode, Percentage
        # FROM ...
        # ORDER BY CountryCode, Percentage DESC
        # ----------------------------------------------------

        if (
            group is not None
            and group.expressions
        ):

            group_columns = [
                expression.copy()
                for expression
                in group.expressions
            ]

            # Replace MAX/MIN projection with its underlying
            # column so output values remain equivalent.
            new_projections = []

            for projection in projections:

                expression = (
                    projection.this
                    if isinstance(
                        projection,
                        exp.Alias,
                    )
                    else projection
                )

                if expression is extreme:
                    new_projections.append(
                        extreme_column.copy()
                    )
                else:
                    new_projections.append(
                        projection.copy()
                    )

            select.set(
                "expressions",
                new_projections,
            )

            # Remove GROUP BY.
            select.set(
                "group",
                None,
            )

            # PostgreSQL DISTINCT ON(group columns).
            select.set(
                "distinct",
                exp.Distinct(
                    on=exp.Tuple(
                        expressions=[
                            expression.copy()
                            for expression
                            in group_columns
                        ]
                    )
                ),
            )

            order_expressions = [
                exp.Ordered(
                    this=expression.copy(),
                    desc=False,
                )
                for expression
                in group_columns
            ]

            order_expressions.append(
                exp.Ordered(
                    this=extreme_column.copy(),
                    desc=is_max,
                )
            )

            select.set(
                "order",
                exp.Order(
                    expressions=order_expressions
                ),
            )

            continue

        # ----------------------------------------------------
        # UNGROUPED case:
        #
        # SELECT MAX(Capacity), Average
        # FROM stadium
        #
        # ->
        #
        # SELECT Capacity, Average
        # FROM stadium
        # ORDER BY Capacity DESC
        # LIMIT 1
        # ----------------------------------------------------

        new_projections = []

        for projection in projections:

            expression = (
                projection.this
                if isinstance(
                    projection,
                    exp.Alias,
                )
                else projection
            )

            if expression is extreme:
                new_projections.append(
                    extreme_column.copy()
                )
            else:
                new_projections.append(
                    projection.copy()
                )

        select.set(
            "expressions",
            new_projections,
        )

        select.set(
            "order",
            exp.Order(
                expressions=[
                    exp.Ordered(
                        this=extreme_column.copy(),
                        desc=is_max,
                    )
                ]
            ),
        )

        select.set(
            "limit",
            exp.Limit(
                expression=exp.Literal.number(
                    1
                )
            ),
        )

    return tree



# ============================================================
# POSTGRESQL SAFE GROUP BY COMPATIBILITY
# ============================================================

def apply_postgres_group_by_compatibility(
    tree,
):
    """
    Repair SQLite GROUP BY queries that PostgreSQL rejects
    because a selected descriptive column is not explicitly
    listed in GROUP BY.

    Example:

        SELECT T2."Name", COUNT(*)
        ...
        GROUP BY T1."Stadium_ID"

    becomes:

        SELECT T2."Name", COUNT(*)
        ...
        GROUP BY T1."Stadium_ID", T2."Name"

    IMPORTANT:

    Queries containing MAX or MIN in the SELECT are skipped
    here because adding descriptive columns can change
    arg-max / arg-min semantics.
    """

    from sqlglot import exp

    for select in tree.find_all(
        exp.Select
    ):

        group = select.args.get(
            "group"
        )

        if group is None:
            continue

        # ----------------------------------------------------
        # Protect arg-max / arg-min style queries.
        # ----------------------------------------------------

        has_max_or_min = any(
            isinstance(
                node,
                (
                    exp.Max,
                    exp.Min,
                ),
            )
            for projection in select.expressions
            for node in projection.walk()
        )

        if has_max_or_min:
            continue

        # ----------------------------------------------------
        # Existing GROUP BY expressions
        # ----------------------------------------------------

        existing_group_sql = {
            expression.sql(
                dialect="postgres"
            )
            for expression in group.expressions
        }

        additions = []

        # ----------------------------------------------------
        # Add plain selected columns that are not aggregates
        # and are not already present in GROUP BY.
        # ----------------------------------------------------

        for projection in select.expressions:

            expression = projection

            if isinstance(
                expression,
                exp.Alias,
            ):
                expression = expression.this

            # Only plain selected columns are handled here.
            # More complex expressions are deliberately left
            # untouched.
            if not isinstance(
                expression,
                exp.Column,
            ):
                continue

            expression_sql = expression.sql(
                dialect="postgres"
            )

            if expression_sql in existing_group_sql:
                continue

            additions.append(
                expression.copy()
            )

            existing_group_sql.add(
                expression_sql
            )

        if additions:

            for expression in additions:
                group.append(
                    "expressions",
                    expression,
                )

    return tree



# ============================================================
# FULL SPIDER -> POSTGRESQL CONVERSION
# ============================================================

def convert_spider_sql(
    sql: str,
    database_name: str,
):
    """
    Parse Spider SQLite SQL, convert identifiers using
    PostgreSQL metadata, and render PostgreSQL SQL.
    """

    import sqlglot

    tree = sqlglot.parse_one(
        sql,
        read="sqlite",
    )

    convert_table_identifiers(
        tree,
        database_name,
    )

    convert_column_identifiers(
        tree,
        database_name,
    )

    apply_postgres_type_compatibility(
        tree,
        database_name,
    )

    apply_sqlite_bare_extreme_compatibility(
        tree,
    )

    apply_postgres_group_by_compatibility(
        tree,
    )

    return tree.sql(
        dialect="postgres"
    )



# ============================================================
# MANUAL TEST
# ============================================================

if __name__ == "__main__":

    metadata = get_identifier_metadata()

    print("=" * 70)
    print("PHASE 7.1D - SQL CONVERTER METADATA")
    print("=" * 70)
    print()

    print(
        "Databases:",
        len(metadata),
    )

    print(
        "Tables:",
        sum(
            len(tables)
            for tables in metadata.values()
        ),
    )

    print()

    pets = metadata["pets_1"]["pets"]

    print(
        "pets_1.pets ->",
        pets["actual_table"],
    )

    print(
        "pettype ->",
        pets["columns"]["pettype"],
    )

    print()
    print(
        "✅ SQL CONVERTER METADATA READY"
    )
    print("=" * 70)
