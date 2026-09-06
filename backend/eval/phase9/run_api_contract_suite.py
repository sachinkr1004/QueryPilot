from fastapi.testclient import TestClient

import main
from db import UnsafeSQLError


client = TestClient(main.app)


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


def run_test(name, test):
    try:
        test()
        print(f"✅ PASS: {name}")
        return True
    except AssertionError as error:
        print(f"❌ FAIL: {name}")
        print(f"   {error}")
        return False


def test_root():
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "message": "QueryPilot backend is running"
    }


def test_query_success():
    main.run_query_pipeline = success_pipeline

    response = client.post(
        "/query",
        json={
            "question": "  What pets do students have?  "
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "success"
    assert body["question"] == "What pets do students have?"
    assert body["database"] == "pets_1"
    assert body["columns"] == ["PetType"]
    assert body["rows"] == [
        ["cat"],
        ["dog"],
    ]
    assert body["correction_used"] is False
    assert body["correction_attempts"] == 0
    assert body["review_used"] is False
    assert body["latency_ms"] == 12.34



def test_legacy_ask_endpoint():
    main.run_query_pipeline = success_pipeline

    response = client.get(
        "/ask",
        params={
            "question": "  What pets do students have?  "
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["status"] == "success"
    assert body["question"] == "What pets do students have?"
    assert body["columns"] == ["PetType"]
    assert body["rows"] == [
        ["cat"],
        ["dog"],
    ]


def test_legacy_ask_empty_question():
    response = client.get(
        "/ask",
        params={"question": "   "},
    )

    assert response.status_code == 422
    assert response.json() == {
        "status": "error",
        "message": "Question must not be empty.",
    }


def test_empty_question():
    response = client.post(
        "/query",
        json={"question": "   "},
    )

    assert response.status_code == 422


def test_missing_question():
    response = client.post(
        "/query",
        json={},
    )

    assert response.status_code == 422


def test_oversized_question():
    response = client.post(
        "/query",
        json={"question": "a" * 1001},
    )

    assert response.status_code == 422


def test_unsafe_sql_is_safe_error():
    secret = "DO_NOT_LEAK_UNSAFE_SQL"

    def unsafe_pipeline(question):
        raise UnsafeSQLError(secret)

    main.run_query_pipeline = unsafe_pipeline

    response = client.post(
        "/query",
        json={"question": "test"},
    )

    assert response.status_code == 500

    body = response.json()

    assert body == {
        "status": "error",
        "message": "Query could not be completed safely.",
    }
    assert secret not in response.text


def test_pipeline_error_is_safe():
    secret = "DO_NOT_LEAK_DATABASE_ERROR"

    def failed_pipeline(question):
        raise RuntimeError(
            {
                "message": secret,
                "database_error": secret,
            }
        )

    main.run_query_pipeline = failed_pipeline

    response = client.post(
        "/query",
        json={"question": "test"},
    )

    assert response.status_code == 500
    assert response.json() == {
        "status": "error",
        "message": "Query processing failed.",
    }
    assert secret not in response.text


def test_unexpected_error_is_safe():
    secret = "DO_NOT_LEAK_INTERNAL_SECRET"

    def broken_pipeline(question):
        raise ValueError(secret)

    main.run_query_pipeline = broken_pipeline

    response = client.post(
        "/query",
        json={"question": "test"},
    )

    assert response.status_code == 500
    assert response.json() == {
        "status": "error",
        "message": "Internal server error.",
    }
    assert secret not in response.text


def main_suite():
    original_pipeline = main.run_query_pipeline

    tests = [
        ("root endpoint works", test_root),
        ("POST /query success contract", test_query_success),
        ("legacy GET /ask works", test_legacy_ask_endpoint),
        ("legacy GET /ask rejects empty question", test_legacy_ask_empty_question),
        ("empty question is rejected", test_empty_question),
        ("missing question is rejected", test_missing_question),
        ("oversized question is rejected", test_oversized_question),
        ("unsafe SQL returns safe error", test_unsafe_sql_is_safe_error),
        ("pipeline error does not leak details", test_pipeline_error_is_safe),
        ("unexpected error does not leak details", test_unexpected_error_is_safe),
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
    print("PHASE 9.13 API CONTRACT SUITE")
    print("=" * 60)
    print(f"Passed: {passed}/{total}")

    if passed != total:
        raise SystemExit(1)

    print()
    print("🎯 All API contract tests passed.")


if __name__ == "__main__":
    main_suite()
