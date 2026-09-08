import logging
import re

from fastapi.testclient import TestClient

import main

from db import UnsafeSQLError


client = TestClient(main.app)


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(self.format(record))


def success_pipeline(question):
    return {
        "database": "pets_1",
        "generated_sql": 'SELECT "PetType" FROM pets_1."Pets";',
        "final_sql": 'SELECT "PetType" FROM pets_1."Pets";',
        "columns": ["PetType"],
        "result": [
            ("cat",),
            ("dog",),
        ],
        "correction_used": False,
        "correction_attempts": 0,
        "latency_ms": 12.34,
    }


def capture_logs(action):
    handler = LogCapture()
    handler.setLevel(logging.INFO)
    main.logger.addHandler(handler)

    try:
        response = action()
        return response, handler.messages
    finally:
        main.logger.removeHandler(handler)


def extract_request_id(message):
    match = re.search(
        r"request_id=([0-9a-f-]{36})",
        message,
    )
    assert match is not None
    return match.group(1)


def run_test(name, test):
    try:
        test()
        print(f"✅ PASS: {name}")
        return True
    except AssertionError as error:
        print(f"❌ FAIL: {name}")
        print(f"   {error}")
        return False


def test_success_log():
    main.run_query_pipeline = success_pipeline

    response, logs = capture_logs(
        lambda: client.post(
            "/query",
            json={"question": "What pets do students have?"},
        )
    )

    assert response.status_code == 200
    assert len(logs) == 1

    message = logs[0]

    assert "event=query_success" in message
    extract_request_id(message)
    assert "database=pets_1" in message
    assert "latency_ms=12.34" in message
    assert "correction_used=False" in message
    assert "correction_attempts=0" in message


def test_request_ids_are_unique():
    main.run_query_pipeline = success_pipeline

    _, first_logs = capture_logs(
        lambda: client.post(
            "/query",
            json={"question": "first"},
        )
    )

    _, second_logs = capture_logs(
        lambda: client.post(
            "/query",
            json={"question": "second"},
        )
    )

    first_id = extract_request_id(first_logs[0])
    second_id = extract_request_id(second_logs[0])

    assert first_id != second_id


def test_success_log_avoids_sensitive_payload():
    secret_question = "SECRET_QUESTION_TEXT"
    secret_sql = "SECRET_SQL_TEXT"
    secret_row = "SECRET_RESULT_ROW"

    def pipeline(question):
        return {
            "database": "pets_1",
            "generated_sql": secret_sql,
            "final_sql": secret_sql,
            "columns": ["value"],
            "result": [(secret_row,)],
            "correction_used": False,
            "correction_attempts": 0,
            "latency_ms": 1.0,
        }

    main.run_query_pipeline = pipeline

    _, logs = capture_logs(
        lambda: client.post(
            "/query",
            json={"question": secret_question},
        )
    )

    combined = "\n".join(logs)

    assert secret_question not in combined
    assert secret_sql not in combined
    assert secret_row not in combined


def test_unsafe_error_log_is_safe():
    secret = "DO_NOT_LEAK_UNSAFE_SQL"

    def pipeline(question):
        raise UnsafeSQLError(secret)

    main.run_query_pipeline = pipeline

    response, logs = capture_logs(
        lambda: client.post(
            "/query",
            json={"question": "test"},
        )
    )

    assert response.status_code == 500
    assert len(logs) == 1

    message = logs[0]

    assert "event=query_failed" in message
    assert "error_type=UnsafeSQLError" in message
    extract_request_id(message)
    assert secret not in message


def test_runtime_error_log_is_safe():
    secret = "DO_NOT_LEAK_DATABASE_ERROR"

    def pipeline(question):
        raise RuntimeError(secret)

    main.run_query_pipeline = pipeline

    response, logs = capture_logs(
        lambda: client.post(
            "/query",
            json={"question": "test"},
        )
    )

    assert response.status_code == 500
    assert len(logs) == 1

    message = logs[0]

    assert "event=query_failed" in message
    assert "error_type=RuntimeError" in message
    extract_request_id(message)
    assert secret not in message


def test_unexpected_error_log_is_safe():
    secret = "DO_NOT_LEAK_INTERNAL_SECRET"

    def pipeline(question):
        raise ValueError(secret)

    main.run_query_pipeline = pipeline

    response, logs = capture_logs(
        lambda: client.post(
            "/query",
            json={"question": "test"},
        )
    )

    assert response.status_code == 500
    assert len(logs) == 1

    message = logs[0]

    assert "event=query_failed" in message
    assert "error_type=ValueError" in message
    extract_request_id(message)
    assert secret not in message


def main_suite():
    original_pipeline = main.run_query_pipeline

    tests = [
        (
            "success request emits useful metadata",
            test_success_log,
        ),
        (
            "request IDs are unique",
            test_request_ids_are_unique,
        ),
        (
            "success logs avoid sensitive payloads",
            test_success_log_avoids_sensitive_payload,
        ),
        (
            "unsafe SQL failure log is safe",
            test_unsafe_error_log_is_safe,
        ),
        (
            "runtime failure log is safe",
            test_runtime_error_log_is_safe,
        ),
        (
            "unexpected failure log is safe",
            test_unexpected_error_log_is_safe,
        ),
    ]

    try:
        results = [
            run_test(name, test)
            for name, test in tests
        ]
    finally:
        main.run_query_pipeline = original_pipeline

    passed = sum(results)
    total = len(results)

    print()
    print("=" * 60)
    print("PHASE 9.14 OBSERVABILITY SUITE")
    print("=" * 60)
    print(f"Passed: {passed}/{total}")

    if passed != total:
        raise SystemExit(1)

    print()
    print("🎯 All observability tests passed.")


if __name__ == "__main__":
    main_suite()
