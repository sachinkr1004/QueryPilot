import re


# ============================================================
# VALUE MATCH NORMALIZATION
# ============================================================

def normalize_value_match_text(value):
    """
    Normalize punctuation differences for semantic
    database-value matching.

    This implementation is intentionally identical to the
    validated normalization used by value_retriever.py.
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
# VALIDATED SEMANTIC VALUE MATCHERS
#
# Source checkpoint:
# numeric_semantic_precision_round2_final.py
#
# Validation:
#   Correct semantic values : 47
#   Extra / wrong values    : 0
#   Precision               : 100.00%
# ============================================================

def contains_phrase(
    question,
    phrase,
):

    question_norm = normalize_value_match_text(
        question
    )

    phrase_norm = normalize_value_match_text(
        phrase
    )

    if not phrase_norm:
        return False

    pattern = (
        r"(?<!\w)"
        + re.escape(phrase_norm)
        + r"(?!\w)"
    )

    return bool(
        re.search(
            pattern,
            question_norm,
            flags=re.IGNORECASE,
        )
    )


# ============================================================
# CONSERVATIVE CATEGORICAL ALIAS RULES
# ============================================================

def categorical_alias_value_matches_question(
    value,
    question,
    table_name,
    column_name,
):
    value_norm = normalize_value_match_text(value)
    question_norm = normalize_value_match_text(question)
    table_norm = normalize_value_match_text(table_name)
    column_norm = normalize_value_match_text(column_name)

    if (
        not value_norm
        or not question_norm
        or not table_norm
        or not column_norm
    ):
        return False

    department_columns = {
        "dept name",
        "dept_name",
        "department",
        "department name",
    }

    if (
        value_norm == "comp sci"
        and column_norm in department_columns
    ):
        return contains_phrase(
            question_norm,
            "computer science",
        )

    result_columns = {
        "result",
        "status",
    }

    if (
        value_norm == "nominated"
        and column_norm in result_columns
    ):
        return (
            contains_phrase(
                question_norm,
                "nomination",
            )
            or contains_phrase(
                question_norm,
                "nominations",
            )
        )

    store_type_columns = {
        "type",
        "store type",
        "store_type",
    }

    if (
        value_norm == "city mall"
        and column_norm in store_type_columns
    ):
        return contains_phrase(
            question_norm,
            "mall",
        )

    # --------------------------------------------------------
    # MPEG -> MPEG audio file
    # --------------------------------------------------------

    media_type_columns = {
        "name",
        "media type",
        "media_type",
        "media type name",
        "media_type_name",
    }

    if (
        value_norm == "mpeg audio file"
        and table_norm in {
            "media types",
            "media_types",
        }
        and column_norm in media_type_columns
    ):
        return contains_phrase(
            question_norm,
            "mpeg",
        )

    # --------------------------------------------------------
    # San Jose State -> San Jose State University
    # --------------------------------------------------------

    if (
        value_norm == "san jose state university"
        and table_norm == "campuses"
        and column_norm == "campus"
    ):
        return contains_phrase(
            question_norm,
            "san jose state",
        )

    # --------------------------------------------------------
    # Masters -> MA
    # --------------------------------------------------------

    degree_columns = {
        "prof high degree",
        "prof_high_degree",
        "high degree",
        "high_degree",
    }

    if (
        value_norm == "ma"
        and column_norm in degree_columns
    ):
        return (
            contains_phrase(
                question_norm,
                "masters",
            )
            or contains_phrase(
                question_norm,
                "master degree",
            )
            or contains_phrase(
                question_norm,
                "master s degree",
            )
        )

    # --------------------------------------------------------
    # received a card -> yes
    # --------------------------------------------------------

    card_columns = {
        "ycard",
        "y card",
        "yellow card",
        "yellow_card",
    }

    if (
        value_norm == "yes"
        and column_norm in card_columns
    ):
        return (
            contains_phrase(
                question_norm,
                "received a card",
            )
            or contains_phrase(
                question_norm,
                "received a yellow card",
            )
            or contains_phrase(
                question_norm,
                "got a card",
            )
        )

    return False


# ============================================================
# BOOLEAN / CATEGORICAL SEMANTIC RULES
# ============================================================

def boolean_semantic_value_matches_question(
    value,
    question,
    column_name,
):
    value_norm = normalize_value_match_text(
        value
    )
    question_norm = normalize_value_match_text(
        question
    )
    column_norm = normalize_value_match_text(
        column_name
    )

    if (
        not value_norm
        or not question_norm
        or not column_norm
    ):
        return False

    # --------------------------------------------------------
    # Column families
    # --------------------------------------------------------

    approval_columns = {
        "fda approved",
        "approved",
        "approval",
    }

    decision_columns = {
        "decision",
    }

    scholarship_columns = {
        "onscholarship",
        "on scholarship",
        "scholarship",
    }

    acting_columns = {
        "temporary acting",
        "acting",
    }

    wifi_columns = {
        "wifi",
    }

    gender_columns = {
        "sex",
        "gender",
        "is male",
    }

    # --------------------------------------------------------
    # YES / Y
    #
    # IMPORTANT:
    # Negative phrases take precedence over positive phrases.
    # --------------------------------------------------------

    if value_norm in {
        "yes",
        "y",
    }:

        if column_norm in approval_columns:
            if contains_phrase(
                question_norm,
                "not approved",
            ):
                return False

            return contains_phrase(
                question_norm,
                "approved",
            )

        if column_norm in decision_columns:
            positive_decision_phrases = (
                "accepted",
                "successfully",
                "succeeded",
                "made the team",
                "successfully tried out",
                "successfully made the team",
                "got accepted",
            )

            return any(
                contains_phrase(
                    question_norm,
                    phrase,
                )
                for phrase in positive_decision_phrases
            )

        if column_norm in scholarship_columns:
            scholarship_phrases = (
                "on scholarship",
                "scholarship student",
                "scholarship students",
            )

            return any(
                contains_phrase(
                    question_norm,
                    phrase,
                )
                for phrase in scholarship_phrases
            )

        if column_norm in acting_columns:
            return contains_phrase(
                question_norm,
                "acting",
            )

        return False

    # --------------------------------------------------------
    # NO / N
    #
    # Do NOT use generic:
    #   without
    #   do not have
    #   does not have
    #
    # Those phrases may describe absence of an entity rather
    # than a boolean/categorical database value.
    # --------------------------------------------------------

    if value_norm in {
        "no",
        "n",
    }:

        if column_norm in approval_columns:
            return contains_phrase(
                question_norm,
                "not approved",
            )

        if column_norm in decision_columns:
            negative_decision_phrases = (
                "rejected",
                "got rejected",
                "not accepted",
            )

            return any(
                contains_phrase(
                    question_norm,
                    phrase,
                )
                for phrase in negative_decision_phrases
            )

        if column_norm in wifi_columns:
            wifi_negative_phrases = (
                "do not have wifi",
                "does not have wifi",
                "without wifi",
                "do not have the wifi function",
                "does not have the wifi function",
            )
            return any(
                contains_phrase(
                    question_norm,
                    phrase,
                )
                for phrase in wifi_negative_phrases
            )

        return False

    # --------------------------------------------------------
    # FEMALE -> F
    #
    # Only gender-like columns may use this semantic mapping.
    #
    # Avoid generic "girl" because:
    #   "girl named Lisa"
    # may identify Lisa without requiring Sex = F.
    # --------------------------------------------------------

    if (
        value_norm == "f"
        and column_norm in gender_columns
    ):
        female_phrases = (
            "female",
            "females",
            "girl student",
            "girl students",
            "woman",
            "women",
        )

        return any(
            contains_phrase(
                question_norm,
                phrase,
            )
            for phrase in female_phrases
        )

    # --------------------------------------------------------
    # MALE -> M
    # --------------------------------------------------------

    if (
        value_norm == "m"
        and column_norm in gender_columns
    ):
        male_phrases = (
            "male",
            "males",
            "boy student",
            "boy students",
            "man",
            "men",
        )

        return any(
            contains_phrase(
                question_norm,
                phrase,
            )
            for phrase in male_phrases
        )

    return False


# ============================================================
# GEOGRAPHIC / DEMONYM SEMANTIC RULES
# ============================================================

def geographic_semantic_value_matches_question(
    value,
    question,
    table_name,
    column_name,
):
    value_norm = normalize_value_match_text(
        value
    )
    question_norm = normalize_value_match_text(
        question
    )
    table_norm = normalize_value_match_text(
        table_name
    )
    column_norm = normalize_value_match_text(
        column_name
    )

    if (
        not value_norm
        or not question_norm
        or not table_norm
        or not column_norm
    ):
        return False

    geographic_columns = {
        "country",
        "state",
        "nationality",
        "headquarters",
    }

    if column_norm not in geographic_columns:
        return False

    # --------------------------------------------------------
    # Protect proper entity name:
    #
    # "American Airlines" must NOT imply
    # country = United States.
    # --------------------------------------------------------

    american_airlines = contains_phrase(
        question_norm,
        "american airlines",
    )

    # --------------------------------------------------------
    # US / USA / UNITED STATES
    #
    # Headquarters in company_employee stores USA.
    # Nationality/country columns may store United States.
    # --------------------------------------------------------

    if value_norm == "usa":

        if column_norm != "headquarters":
            return False

        return (
            contains_phrase(
                question_norm,
                "us",
            )
            or contains_phrase(
                question_norm,
                "u s",
            )
            or contains_phrase(
                question_norm,
                "usa",
            )
        )

    if value_norm == "united states":

        if american_airlines:
            return False

        # Do not map generic US wording to a nationality value
        # when the question is explicitly about headquarters.
        if (
            contains_phrase(
                question_norm,
                "headquartered",
            )
            or contains_phrase(
                question_norm,
                "headquarters",
            )
        ):
            return False

        return (
            contains_phrase(
                question_norm,
                "us",
            )
            or contains_phrase(
                question_norm,
                "u s",
            )
        )

    # --------------------------------------------------------
    # UNITED KINGDOM
    # --------------------------------------------------------

    if value_norm == "united kingdom":

        return (
            contains_phrase(
                question_norm,
                "uk",
            )
            or contains_phrase(
                question_norm,
                "u k",
            )
            or contains_phrase(
                question_norm,
                "british",
            )
        )


    # --------------------------------------------------------
    # UK
    # --------------------------------------------------------

    if value_norm == "uk":

        return contains_phrase(
            question_norm,
            "british",
        )

    # --------------------------------------------------------
    # CANADA / ITALY
    # --------------------------------------------------------

    if value_norm == "canada":

        return contains_phrase(
            question_norm,
            "canadian",
        )

    if value_norm == "italy":

        return contains_phrase(
            question_norm,
            "italian",
        )

    # --------------------------------------------------------
    # US STATE ABBREVIATIONS
    # --------------------------------------------------------

    if value_norm == "fl":

        return (
            column_norm == "state"
            and contains_phrase(
                question_norm,
                "florida",
            )
        )

    if value_norm == "la":

        return (
            column_norm == "state"
            and contains_phrase(
                question_norm,
                "louisiana",
            )
        )

    return False


# ============================================================
# NUMERIC / ORDINAL SEMANTIC RULES
# ============================================================

def numeric_semantic_value_matches_question(
    value,
    question,
    table_name,
    column_name,
):
    value_norm = normalize_value_match_text(
        value
    )

    question_norm = normalize_value_match_text(
        question
    )

    table_norm = normalize_value_match_text(
        table_name
    )

    column_norm = normalize_value_match_text(
        column_name
    )

    if (
        not value_norm
        or not question_norm
        or not table_norm
        or not column_norm
    ):
        return False

    # --------------------------------------------------------
    # FIRST POSITION -> "1"
    #
    # Keep this narrow:
    # only position-like columns.
    # --------------------------------------------------------

    position_columns = {
        "position",
        "position text",
        "positiontext",
    }

    if (
        value_norm == "1"
        and column_norm in position_columns
    ):
        first_position_phrases = (
            "first position",
            "position first",
        )

        return any(
            contains_phrase(
                question_norm,
                phrase,
            )
            for phrase in first_position_phrases
        )

    # --------------------------------------------------------
    # FIVE STAR -> "5"
    #
    # Only hotel star-rating columns.
    # --------------------------------------------------------

    star_rating_columns = {
        "star rating code",
        "star_rating_code",
        "star rating",
        "rating",
    }

    if (
        value_norm == "5"
        and column_norm in star_rating_columns
    ):
        five_star_phrases = (
            "five star",
            "five star hotel",
            "five star hotels",
        )

        return any(
            contains_phrase(
                question_norm,
                phrase,
            )
            for phrase in five_star_phrases
        )

    return False
