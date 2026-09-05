import re
import difflib
import sqlite3

from functools import lru_cache

from finetuning.spider_context import (
    build_database_metadata,
    get_sqlite_database_path,
)

from finetuning.semantic_value_matcher import (
    categorical_alias_value_matches_question,
    boolean_semantic_value_matches_question,
    geographic_semantic_value_matches_question,
    numeric_semantic_value_matches_question,
)


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_text(value):
    return re.sub(
        r"\s+",
        " ",
        str(value).strip().lower(),
    )


# ============================================================
# SAFE VALUE ALIASES
# ============================================================

VALUE_ALIASES = {
    "f": (
        "female",
    ),
    "m": (
        "male",
    ),
    "usa": (
        "us",
        "united states",
    ),
    "los angeles": (
        "la",
    ),
    "ca": (
        "california",
    ),
    "il": (
        "illinois",
    ),
}


def alias_occurs_in_question(
    alias: str,
    question: str,
):
    """
    Check whether an alias occurs as a complete token/phrase.

    Boundary matching prevents short aliases such as:

        US
        LA

    from matching inside larger words.
    """

    normalized_alias = normalize_text(
        alias
    )

    normalized_question = normalize_text(
        question
    )

    if not normalized_alias:
        return False

    pattern = (
        r"(?<!\w)"
        + re.escape(normalized_alias)
        + r"(?!\w)"
    )

    return bool(
        re.search(
            pattern,
            normalized_question,
            flags=re.IGNORECASE,
        )
    )


def value_alias_matches_question(
    value,
    question: str,
):
    """
    Match an existing database value using a controlled alias.
    """

    normalized_value = normalize_text(
        value
    )

    aliases = VALUE_ALIASES.get(
        normalized_value,
        (),
    )

    return any(
        alias_occurs_in_question(
            alias,
            question,
        )
        for alias in aliases
    )



# ============================================================
# VALUE MATCH NORMALIZATION
# ============================================================

def normalize_value_match_text(value):
    """
    Normalize punctuation differences for value matching.

    Examples:
        Tokyo,Japan   -> tokyo japan
        tokyo , japan -> tokyo japan
        Ph.D.         -> ph d
    """

    value = str(value).strip().lower()

    value = re.sub(
        r"[^a-z0-9]+",
        " ",
        value,
    )

    return " ".join(
        value.split()
    )



# ============================================================
# CONSERVATIVE FUZZY VALUE MATCHING
# ============================================================

def fuzzy_value_matches_question(
    value,
    question: str,
    threshold: float = 0.90,
):
    """
    Conservative fuzzy matching for database values.

    This is intended only for small spelling or formatting
    differences such as:

        Billy Cobam      -> Billy Cobham
        Ball to the Wall -> Balls to the Wall
        Annual Meeting   -> Annaual Meeting

    Short values are excluded because fuzzy matching values
    such as F, M, CA, IL, etc. would create false positives.
    """

    normalized_value = normalize_value_match_text(
        value
    )

    normalized_question = normalize_value_match_text(
        question
    )

    if not normalized_value:
        return False

    # Do not fuzzy-match short values.
    if len(normalized_value) <= 3:
        return False

    value_words = normalized_value.split()
    question_words = normalized_question.split()

    if not value_words or not question_words:
        return False

    # Compare the DB value against question n-grams
    # near the same word length.
    min_size = max(
        1,
        len(value_words) - 1,
    )

    max_size = min(
        len(question_words),
        len(value_words) + 1,
    )

    best_ratio = 0.0

    for size in range(
        min_size,
        max_size + 1,
    ):
        for start in range(
            0,
            len(question_words) - size + 1,
        ):
            phrase = " ".join(
                question_words[
                    start:start + size
                ]
            )

            ratio = difflib.SequenceMatcher(
                None,
                normalized_value,
                phrase,
            ).ratio()

            best_ratio = max(
                best_ratio,
                ratio,
            )

    return best_ratio >= threshold



# ============================================================
# LIKE PATTERN GROUNDING
# ============================================================

def like_pattern_core(

    pattern,

):

    """
    Extract the literal core from a SQL LIKE pattern.

    Examples:

        %Swift% -> Swift
        A%      -> A
        %m      -> m
        8/%     -> 8/
    """

    value = str(pattern)

    if value.startswith("%"):
        value = value[1:]

    if value.endswith("%"):
        value = value[:-1]

    return value


def classify_like_pattern(

    pattern,

):

    """
    Classify the wildcard shape of a SQL LIKE pattern.

    Returns:

        contains
        prefix
        suffix
        internal
        None
    """

    value = str(pattern)

    if "%" not in value:
        return None

    starts = value.startswith("%")
    ends = value.endswith("%")

    if starts and ends:
        return "contains"

    if ends:
        return "prefix"

    if starts:
        return "suffix"

    return "internal"


def like_pattern_matches_question(

    pattern,

    question: str,

):

    """
    Determine whether the literal core of a LIKE pattern
    occurs directly in the natural-language question.

    This intentionally handles only directly grounded
    patterns.

    Examples:

        %Swift% -> question contains "Swift"
        A%      -> question contains "A"
        %m      -> question contains "m"

    Semantic conversions such as:

        August -> 8/%

    are intentionally handled separately.
    """

    category = classify_like_pattern(
        pattern
    )

    if category is None:
        return False

    core = like_pattern_core(
        pattern
    )

    normalized_core = normalize_value_match_text(
        core
    )

    normalized_question = normalize_value_match_text(
        question
    )

    if not normalized_core:
        return False

    # Protect very short pattern cores such as:
    #
    # A%
    # %m
    # 2%
    #
    # from accidental substring matches.

    if len(normalized_core) <= 2:

        token_pattern = (
            r"(?<!\w)"
            + re.escape(normalized_core)
            + r"(?!\w)"
        )

        return bool(
            re.search(
                token_pattern,
                normalized_question,
                flags=re.IGNORECASE,
            )
        )

    return (
        normalized_core
        in normalized_question
    )



# ============================================================
# SEMANTIC DATE LIKE GROUNDING
# ============================================================

MONTH_LIKE_PREFIXES = {
    "january": "1/",
    "february": "2/",
    "march": "3/",
    "april": "4/",
    "may": "5/",
    "june": "6/",
    "july": "7/",
    "august": "8/",
    "september": "9/",
    "october": "10/",
    "november": "11/",
    "december": "12/",
}


def semantic_like_pattern_matches_question(

    pattern,

    question: str,

):

    """
    Match deterministic semantic LIKE patterns.

    Currently supports month names mapped to date prefixes:

        August   -> 8/%
        December -> 12/%

    The mapping is intentionally narrow and deterministic.
    """

    category = classify_like_pattern(
        pattern
    )

    if category != "prefix":
        return False

    core = like_pattern_core(
        pattern
    )

    normalized_core = str(
        core
    ).strip().lower()

    normalized_question = normalize_value_match_text(
        question
    )

    for month, prefix in MONTH_LIKE_PREFIXES.items():

        if (
            normalized_core == prefix
            and re.search(
                r"(?<!\\w)"
                + re.escape(month)
                + r"(?!\\w)",
                normalized_question,
                flags=re.IGNORECASE,
            )
        ):
            return True

    return False


def fuzzy_like_pattern_matches_question(

    pattern,

    question: str,

    threshold: float = 0.88,

):

    """
    Conservative fuzzy grounding for genuine SQL LIKE patterns.

    Only patterns containing % are considered.

    Example:

        %International%
        question: Interanation
            -> match at similarity >= 0.88

    Ordinary values containing underscores such as:

        MK_MAN
        PU_MAN

    are intentionally excluded.
    """

    pattern_text = str(pattern)

    if "%" not in pattern_text:
        return False

    core = like_pattern_core(
        pattern_text
    )

    normalized_core = normalize_value_match_text(
        core
    )

    normalized_question = normalize_value_match_text(
        question
    )

    if not normalized_core:
        return False

    # Avoid fuzzy matching tiny pattern cores.
    if len(normalized_core) <= 3:
        return False

    core_words = normalized_core.split()
    question_words = normalized_question.split()

    if not core_words or not question_words:
        return False

    min_size = max(
        1,
        len(core_words) - 1,
    )

    max_size = min(
        len(question_words),
        len(core_words) + 1,
    )

    best_score = 0.0

    for size in range(
        min_size,
        max_size + 1,
    ):
        for start in range(
            len(question_words) - size + 1
        ):
            phrase = " ".join(
                question_words[
                    start:start + size
                ]
            )

            score = difflib.SequenceMatcher(
                None,
                normalized_core,
                phrase,
            ).ratio()

            best_score = max(
                best_score,
                score,
            )

    return best_score >= threshold



def grounded_like_pattern_matches_question(

    pattern,

    question: str,

):

    """
    Combined LIKE grounding.

    First try direct lexical grounding, then deterministic
    semantic grounding.
    """

    return (
        like_pattern_matches_question(
            pattern,
            question,
        )
        or semantic_like_pattern_matches_question(
            pattern,
            question,
        )
        or fuzzy_like_pattern_matches_question(
            pattern,
            question,
            threshold=0.88,
        )
    )



# ============================================================
# DISTINCT VALUES
# ============================================================

@lru_cache(maxsize=None)
def get_distinct_values(
    database_name: str,
    table_name: str,
    column_name: str,
    limit: int = 200,
):
    """
    Load distinct non-null values for one SQLite column.

    Cached because the same columns may be inspected across
    many training questions.
    """

    path = get_sqlite_database_path(
        database_name
    )

    conn = sqlite3.connect(
        path
    )

    cursor = conn.cursor()

    query = (
        f'SELECT DISTINCT "{column_name}" '
        f'FROM "{table_name}" '
        f'WHERE "{column_name}" IS NOT NULL '
        f'LIMIT {int(limit)}'
    )

    try:
        cursor.execute(query)

        values = [
            row[0]
            for row in cursor.fetchall()
        ]

    finally:
        cursor.close()
        conn.close()

    return tuple(values)


# ============================================================
# SAFE MULTI-TOKEN CUTOFF FALLBACK
# ============================================================

def multitoken_boundary_match(
    value,
    question: str,
):
    """
    Conservative exact fallback matcher.

    Only multi-token database values are eligible. This avoids
    the single-token noise observed during full-column audits.
    """

    value_norm = normalize_value_match_text(
        value
    )

    question_norm = normalize_value_match_text(
        question
    )

    if not value_norm:
        return False

    # Single-token values are intentionally excluded.
    if len(value_norm.split()) < 2:
        return False

    pattern = (
        r"(?<!\w)"
        + re.escape(value_norm)
        + r"(?!\w)"
    )

    return bool(
        re.search(
            pattern,
            question_norm,
            flags=re.IGNORECASE,
        )
    )


def remove_nested_value_matches(
    values,
):
    """
    Prefer the longest exact value when one matched value is
    fully contained inside another.

    Example:
        New York
        York

    keeps:
        New York
    """

    normalized = [
        (
            value,
            normalize_value_match_text(
                value
            ),
        )
        for value in values
        if normalize_value_match_text(
            value
        )
    ]

    normalized.sort(
        key=lambda item: len(item[1]),
        reverse=True,
    )

    kept = []

    for value, value_norm in normalized:

        nested = False

        for _, kept_norm in kept:

            pattern = (
                r"(?<!\w)"
                + re.escape(value_norm)
                + r"(?!\w)"
            )

            if re.search(
                pattern,
                kept_norm,
                flags=re.IGNORECASE,
            ):
                nested = True
                break

        if not nested:
            kept.append(
                (
                    value,
                    value_norm,
                )
            )

    return [
        value
        for value, _ in kept
    ]


def full_column_multitoken_fallback(
    database_name: str,
    table_name: str,
    column_name: str,
    question: str,
):
    """
    Scan the full text column only when the normal 200-value
    retrieval window is full.

    The fallback uses exact multi-token boundary grounding and
    removes nested shorter matches.
    """

    first_values = get_distinct_values(
        database_name,
        table_name,
        column_name,
        limit=200,
    )

    # Fewer than 200 means there is no evidence that the normal
    # retrieval window was truncated.
    if len(first_values) < 200:
        return []

    path = get_sqlite_database_path(
        database_name
    )

    conn = sqlite3.connect(
        path
    )

    try:
        cursor = conn.cursor()

        query = (
            f'SELECT DISTINCT "{column_name}" '
            f'FROM "{table_name}" '
            f'WHERE "{column_name}" IS NOT NULL'
        )

        try:
            cursor.execute(
                query
            )
        except sqlite3.Error:
            return []

        question_norm = normalize_value_match_text(
            question
        )
        question_padded = (
            f" {question_norm} "
        )

        matches = []
        for row in cursor.fetchall():
            value = row[0]
            value_norm = normalize_value_match_text(
                value
            )

            if not value_norm:
                continue

            # Preserve the existing fallback rule:
            # single-token values are not eligible.
            if len(value_norm.split()) < 2:
                continue

            # Equivalent to the previous normalized
            # word-boundary regex without running one
            # regex per database value.
            if (
                f" {value_norm} "
                in question_padded
            ):
                matches.append(
                    value
                )

        return remove_nested_value_matches(
            matches
        )

    finally:
        conn.close()


# ============================================================
# SAFE COLUMN-AWARE MORPHOLOGY
# ============================================================

PERSON_NAME_COLUMNS = {
    "first_name",
    "firstname",
    "fname",
    "last_name",
    "lastname",
    "lname",
    "forename",
    "surname",
}


def morphology_allowed_for_column(
    column_name,
):
    """
    Block morphology on high-confidence person-name columns.

    This prevents risky transformations such as:

        Luca -> Lucas
        Jame -> James

    while still allowing ordinary singular/plural grounding
    on other text columns.
    """

    normalized_column = (
        str(column_name)
        .strip()
        .lower()
    )

    return (
        normalized_column
        not in PERSON_NAME_COLUMNS
    )


def morphology_forms(
    word,
):
    """
    Conservative singular/plural forms.

    Examples:
        egg   -> eggs
        eggs  -> egg
        herb  -> herbs
        herbs -> herb
    """

    word = normalize_value_match_text(
        word
    )

    if (
        not word
        or " " in word
        or len(word) < 3
        or not word.isalpha()
    ):
        return set()

    forms = set()

    # Singular -> plural
    if word.endswith(
        (
            "s",
            "x",
            "z",
            "ch",
            "sh",
        )
    ):
        forms.add(
            word + "es"
        )
    else:
        forms.add(
            word + "s"
        )

    # Plural -> singular
    if (
        word.endswith("es")
        and len(word) > 4
    ):
        forms.add(
            word[:-2]
        )

    if (
        word.endswith("s")
        and not word.endswith("ss")
        and len(word) > 3
    ):
        forms.add(
            word[:-1]
        )

    forms.discard(
        word
    )

    return {
        form
        for form in forms
        if len(form) >= 3
    }


def morphology_value_matches_question(
    value,
    question: str,
):
    """
    Conservative single-token morphology grounding.

    Exact matches are handled elsewhere.
    This function only handles singular/plural variants.
    """

    value_norm = normalize_value_match_text(
        value
    )

    question_norm = normalize_value_match_text(
        question
    )

    if (
        not value_norm
        or " " in value_norm
        or not value_norm.isalpha()
    ):
        return False

    question_tokens = {
        token
        for token in question_norm.split()
        if token
    }

    # Exact match is not a morphology match.
    if value_norm in question_tokens:
        return False

    for form in morphology_forms(
        value_norm
    ):
        if form in question_tokens:
            return True

    for token in question_tokens:

        if (
            value_norm
            in morphology_forms(token)
        ):
            return True

    return False


# ============================================================
# SIMPLE VALUE MATCHING
# ============================================================

def value_matches_question(
    value,
    question: str,
):
    """
    Conservative lexical grounding with
    punctuation-aware normalization.

    Short values still require token boundaries to avoid
    accidental matches:

        F  must not match "for"
        M  must not match "many"
        CA must not match inside another word

    Longer values use punctuation-normalized matching:

        Tokyo,Japan
        tokyo , japan
            -> tokyo japan
    """

    normalized_value = normalize_value_match_text(
        value
    )

    normalized_question = normalize_value_match_text(
        question
    )

    if not normalized_value:
        return False

    # --------------------------------------------------------
    # Protect short database values from substring matches.
    # --------------------------------------------------------

    if len(normalized_value) <= 3:

        pattern = (
            r"(?<!\w)"
            + re.escape(normalized_value)
            + r"(?!\w)"
        )

        return bool(
            re.search(
                pattern,
                normalized_question,
                flags=re.IGNORECASE,
            )
        )

    # --------------------------------------------------------
    # Longer values may safely use substring matching.
    # --------------------------------------------------------

    return (
        normalized_value
        in normalized_question
    )



# ============================================================
# RETRIEVE QUESTION-RELEVANT VALUES
# ============================================================

def retrieve_relevant_values(
    question: str,
    database_name: str,
    table_names,
    max_values_per_column: int = 5,
):
    """
    Search text-like columns in the retrieved schema tables and
    return values that lexically occur in the question.

    Output:
        [
            {
                "table_name": ...,
                "column_name": ...,
                "values": [...]
            }
        ]
    """

    metadata = build_database_metadata(
        database_name
    )

    results = []

    selected_tables = {
        table_name.lower()
        for table_name in table_names
    }

    for table_name, table_info in (
        metadata["tables"].items()
    ):

        if (
            table_name.lower()
            not in selected_tables
        ):
            continue

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

            # Spider schema types:
            # text / number / time / boolean / others
            #
            # Start conservatively with text only.
            if (
                str(column_type).lower()
                != "text"
            ):
                continue

            values = get_distinct_values(
                database_name,
                table_name,
                column_name,
            )

            matches = []

            for value in values:

                if (
                    value_matches_question(
                        value,
                        question,
                    )
                    or value_alias_matches_question(
                        value,
                        question,
                    )
                    or fuzzy_value_matches_question(
                        value,
                        question,
                        threshold=0.90,
                    )
                    or (
                        morphology_allowed_for_column(
                            column_name
                        )
                        and morphology_value_matches_question(
                            value,
                            question,
                        )
                    )
                    or categorical_alias_value_matches_question(
                        value,
                        question,
                        table_name,
                        column_name,
                    )
                    or boolean_semantic_value_matches_question(
                        value,
                        question,
                        column_name,
                    )
                    or geographic_semantic_value_matches_question(
                        value,
                        question,
                        table_name,
                        column_name,
                    )
                    or numeric_semantic_value_matches_question(
                        value,
                        question,
                        table_name,
                        column_name,
                    )
                ):
                    matches.append(
                        value
                    )

                if (
                    len(matches)
                    >= max_values_per_column
                ):
                    break


            # ------------------------------------------------
            # Safe multi-token cutoff fallback.
            #
            # The ordinary retriever scans the first 200
            # distinct values. A full 200-value window may
            # mean that a relevant value was truncated.
            #
            # The fallback is conservative:
            #   - multi-token values only
            #   - exact normalized boundary match
            #   - nested shorter matches removed
            # ------------------------------------------------

            if (
                len(values) == 200
                and len(matches)
                < max_values_per_column
            ):
                fallback_matches = (
                    full_column_multitoken_fallback(
                        database_name=database_name,
                        table_name=table_name,
                        column_name=column_name,
                        question=question,
                    )
                )

                existing_normalized = {
                    normalize_value_match_text(
                        value
                    )
                    for value in matches
                }

                for fallback_value in fallback_matches:

                    normalized_fallback = (
                        normalize_value_match_text(
                            fallback_value
                        )
                    )

                    if (
                        normalized_fallback
                        in existing_normalized
                    ):
                        continue

                    matches.append(
                        fallback_value
                    )

                    existing_normalized.add(
                        normalized_fallback
                    )

                    if (
                        len(matches)
                        >= max_values_per_column
                    ):
                        break

            if matches:

                results.append(
                    {
                        "table_name": table_name,
                        "column_name": column_name,
                        "values": matches,
                    }
                )

    return results


# ============================================================
# FORMAT VALUE CONTEXT
# ============================================================

def format_value_context(
    value_matches,
):
    """
    Convert retrieved value matches into model-readable text.
    """

    if not value_matches:
        return "None"

    lines = []

    for item in value_matches:

        values = ", ".join(
            repr(value)
            for value in item["values"]
        )

        lines.append(
            f"- "
            f"{item['table_name']}."
            f"{item['column_name']}: "
            f"{values}"
        )

    return "\n".join(
        lines
    )


# ============================================================
# MANUAL TEST
# ============================================================

if __name__ == "__main__":

    tests = [
        (
            "department_management",
            (
                "What are the names of the heads "
                "who are born outside the California state?"
            ),
            ["head"],
        ),
        (
            "farm",
            (
                "Show the census ranking of cities "
                "whose status are not Village."
            ),
            ["city"],
        ),
        (
            "bike_1",
            (
                "What are the ids of stations "
                "located in San Francisco?"
            ),
            ["station"],
        ),
        (
            "bike_1",
            (
                "In zip code 94107, on which day "
                "neither Fog nor Rain was observed?"
            ),
            ["weather"],
        ),
    ]

    print("=" * 90)
    print("PHASE 7.2J.2B - VALUE RETRIEVER TEST")
    print("=" * 90)

    for db_id, question, tables in tests:

        matches = retrieve_relevant_values(
            question=question,
            database_name=db_id,
            table_names=tables,
        )

        print()
        print("-" * 90)
        print("Database :", db_id)
        print("Question :", question)
        print("Tables   :", tables)

        print()
        print("VALUE CONTEXT:")
        print(
            format_value_context(
                matches
            )
        )

    print()
    print("=" * 90)
    print("✅ VALUE RETRIEVER TEST COMPLETE")
    print("=" * 90)
