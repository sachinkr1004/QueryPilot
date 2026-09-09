import main
from fastapi.testclient import TestClient
from db import UnsafeSQLError


client = TestClient(main.app)


EXPECTED_RESPONSE_KEYS = {
    "status",
    "question",
    "database",
    "generated_sql",
    "final_sql",
    "columns",
    "rows",
    "correction_used",
    "correction_attempts",
    "review_used",
    "latency_ms",
}


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


def test_api_identity():
    schema = main.app.openapi()

    assert schema["info"]["title"] == "QueryPilot API"
    assert schema["info"]["version"] == "1.0.0"


def test_public_routes_and_methods():
    schema = main.app.openapi()

    actual = {
        path: {
            method.upper()
            for method in methods
        }
        for path, methods in schema["paths"].items()
    }

    assert actual == {
        "/": {"GET"},
        "/query": {"POST"},
        "/ask": {"GET"},
    }


def test_query_request_schema():
    schema = main.app.openapi()
    request = schema["components"]["schemas"]["QueryRequest"]

    assert request["type"] == "object"
    assert request["required"] == ["question"]

    question = request["properties"]["question"]

    assert question["type"] == "string"
    assert question["minLength"] == 1
    assert question["maxLength"] == 1000


def test_query_response_schema():
    schema = main.app.openapi()
    response = schema["components"]["schemas"]["QueryResponse"]

    assert response["type"] == "object"
    assert set(response["properties"]) == EXPECTED_RESPONSE_KEYS
    assert set(response["required"]) == EXPECTED_RESPONSE_KEYS

    properties = response["properties"]

    assert properties["status"]["const"] == "success"
    assert properties["question"]["type"] == "string"
    assert properties["database"]["type"] == "string"
    assert properties["generated_sql"]["type"] == "string"
    assert properties["final_sql"]["type"] == "string"
    assert properties["columns"]["type"] == "array"
    assert properties["columns"]["items"]["type"] == "string"
    assert properties["rows"]["type"] == "array"
    assert properties["correction_used"]["type"] == "boolean"
    assert properties["correction_attempts"]["type"] == "integer"
    assert properties["review_used"]["type"] == "boolean"
    assert properties["latency_ms"]["type"] == "number"


def test_query_success_runtime_contract():
    main.run_query_pipeline = success_pipeline

    response = client.post(
        "/query",
        json={
            "question": "  What pets do students have?  "
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert set(body) == EXPECTED_RESPONSE_KEYS
    assert body == {
        "status": "success",
        "question": "What pets do students have?",
        "database": "pets_1",
        "generated_sql": 'SELECT "PetType" FROM pets_1."Pets";',
        "final_sql": 'SELECT "PetType" FROM pets_1."Pets";',
        "columns": ["PetType"],
        "rows": [
            ["cat"],
            ["dog"],
        ],
        "correction_used": False,
        "correction_attempts": 0,
        "review_used": False,
        "latency_ms": 12.34,
    }


def test_query_validation_contract():
    empty = client.post(
        "/query",
        json={"question": "   "},
    )
    missing = client.post(
        "/query",
        json={},
    )
    oversized = client.post(
        "/query",
        json={"question": "a" * 1001},
    )

    assert empty.status_code == 422
    assert missing.status_code == 422
    assert oversized.status_code == 422


def test_legacy_ask_contract():
    main.run_query_pipeline = success_pipeline

    response = client.get(
        "/ask",
        params={
            "question": "  What pets do students have?  "
        },
    )

    assert response.status_code == 200
    assert set(response.json()) == EXPECTED_RESPONSE_KEYS
    assert response.json()["question"] == "What pets do students have?"


def test_legacy_validation_contract():
    empty = client.get(
        "/ask",
        params={"question": "   "},
    )
    oversized = client.get(
        "/ask",
        params={"question": "a" * 1001},
    )

    assert empty.status_code == 422
    assert empty.json() == {
        "status": "error",
        "message": "Question must not be empty.",
    }

    assert oversized.status_code == 422
    assert oversized.json() == {
        "status": "error",
        "message": "Question must be at most 1000 characters.",
    }


def test_safe_runtime_error_contract():
    cases = [
        (
            UnsafeSQLError("DO_NOT_LEAK_UNSAFE"),
            "Query could not be completed safely.",
        ),
        (
            RuntimeError("DO_NOT_LEAK_RUNTIME"),
            "Query processing failed.",
        ),
        (
            ValueError("DO_NOT_LEAK_INTERNAL"),
            "Internal server error.",
        ),
    ]

    for error, expected_message in cases:
        def failed_pipeline(question, error=error):
            raise error

        main.run_query_pipeline = failed_pipeline

        response = client.post(
            "/query",
            json={"question": "test"},
        )

        assert response.status_code == 500
        assert response.json() == {
            "status": "error",
            "message": expected_message,
        }

        assert str(error) not in response.text


def test_root_contract():
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "message": "QueryPilot backend is running"
    }


def main_suite():
    original_pipeline = main.run_query_pipeline

    tests = [
        ("API identity frozen", test_api_identity),
        ("public routes and methods frozen", test_public_routes_and_methods),
        ("query request schema frozen", test_query_request_schema),
        ("query response schema frozen", test_query_response_schema),
        ("POST /query runtime contract frozen", test_query_success_runtime_contract),
        ("POST /query validation frozen", test_query_validation_contract),
        ("legacy GET /ask contract frozen", test_legacy_ask_contract),
        ("legacy GET /ask validation frozen", test_legacy_validation_contract),
        ("safe runtime errors frozen", test_safe_runtime_error_contract),
        ("root contract frozen", test_root_contract),
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
    print("PHASE 9.18 API CONTRACT FREEZE SUITE")
    print("=" * 60)
    print(f"Passed: {passed}/{total}")

    if passed != total:
        raise SystemExit(1)

    print()
    print("🎯 QueryPilot API v1.0.0 contract is frozen.")


if __name__ == "__main__":
    main_suite()
