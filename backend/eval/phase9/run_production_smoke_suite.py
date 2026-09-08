from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


SMOKE_CASES = [
    {
        "name": "simple_select",
        "question": "List the names and ages of all singers.",
        "expected_database": "concert_singer",
    },
    {
        "name": "aggregation",
        "question": "How many employees are there in each city?",
        "expected_database": "employee_hire_evaluation",
    },
    {
        "name": "join",
        "question": "Show each car maker's full name and its country name.",
        "expected_database": "car_1",
    },
]


def run_case(case):
    response = client.post(
        "/query",
        json={
            "question": case["question"],
        },
    )

    if response.status_code != 200:
        raise AssertionError(
            f"{case['name']}: HTTP {response.status_code}: "
            f"{response.text}"
        )

    data = response.json()

    assert data["status"] == "success", (
        f"{case['name']}: unexpected status"
    )

    assert data["database"] == case["expected_database"], (
        f"{case['name']}: expected database "
        f"{case['expected_database']}, got {data['database']}"
    )

    assert isinstance(data["generated_sql"], str)
    assert data["generated_sql"].strip()

    assert isinstance(data["final_sql"], str)
    assert data["final_sql"].strip()

    assert isinstance(data["columns"], list)
    assert isinstance(data["rows"], list)

    assert isinstance(data["correction_used"], bool)
    assert isinstance(data["correction_attempts"], int)

    assert data["review_used"] is False

    assert isinstance(data["latency_ms"], (int, float))
    assert data["latency_ms"] >= 0

    return data


def main():
    passed = 0

    print("=" * 80)
    print("PHASE 9.16 — PRODUCTION LIVE SMOKE")
    print("=" * 80)

    for index, case in enumerate(SMOKE_CASES, start=1):
        print()
        print(
            f"[{index}/{len(SMOKE_CASES)}] "
            f"{case['name']}"
        )

        try:
            data = run_case(case)
        except Exception as error:
            print("❌ FAIL")
            print("Error type:", type(error).__name__)
            print("Error:", str(error))
            raise

        passed += 1

        print("✅ PASS")
        print("Database           :", data["database"])
        print("Columns returned   :", len(data["columns"]))
        print("Rows returned      :", len(data["rows"]))
        print("Correction used    :", data["correction_used"])
        print("Correction attempts:", data["correction_attempts"])
        print("Latency ms         :", data["latency_ms"])

    print()
    print("=" * 80)
    print(f"RESULT: {passed}/{len(SMOKE_CASES)} PASS")
    print("=" * 80)


if __name__ == "__main__":
    main()
