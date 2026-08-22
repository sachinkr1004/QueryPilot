"""
QueryPilot Phase 7.2

Frozen full-scale Spider split.

Source:
    train_spider.json

Original:
    7000 examples
    140 databases

Frozen holdout:
    640 examples
    14 databases

Final training:
    6360 examples
    126 databases
"""


# ============================================================
# FROZEN HOLDOUT DATABASES
# ============================================================

FULL_SCALE_HOLDOUT_DATABASES = {
    "activity_1",
    "chinook_1",
    "baseball_1",
    "club_1",
    "aircraft",
    "behavior_monitoring",
    "candidate_poll",
    "city_record",
    "climbing",
    "cinema",
    "body_builder",
    "book_2",
    "browser_web",
    "architecture",
}


# ============================================================
# CONSTANTS
# ============================================================

EXPECTED_SOURCE_EXAMPLES = 7000

EXPECTED_SOURCE_DATABASES = 140

EXPECTED_HOLDOUT_EXAMPLES = 640

EXPECTED_HOLDOUT_DATABASES = 14

EXPECTED_TRAIN_EXAMPLES = 6360

EXPECTED_TRAIN_DATABASES = 126
