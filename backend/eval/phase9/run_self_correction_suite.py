"""Phase 9.10 deterministic production self-correction regression suite."""

from db import UnsafeSQLError
from production import pipeline


def run_case(
    name,
    generated_sql,
    execution_plan,
    corrected_sql=None,
    expected_exception=None,
    expected_corrections=0,
    expected_executions=1,
):
    original_functions = {
        "retrieve_schema": pipeline.retrieve_schema,
        "retrieve_examples": pipeline.retrieve_examples,
        "generate_sql": pipeline.generate_sql,
        "correct_sql": pipeline.correct_sql,
        "execute_query": pipeline.execute_query,
    }

    calls = {
        "correct_sql": 0,
        "execute_query": 0,
    }

    execution_index = 0

    try:
        pipeline.retrieve_schema = lambda question: (
            "test_db",
            "Table: test_db.items\nColumns:\n- id: integer",
            0.0,
        )

        pipeline.retrieve_examples = (
            lambda *args, **kwargs: []
        )

        pipeline.generate_sql = (
            lambda *args, **kwargs: generated_sql
        )

        def fake_correct_sql(**kwargs):
            calls["correct_sql"] += 1
            return corrected_sql

        pipeline.correct_sql = fake_correct_sql

        def fake_execute_query(sql):
            nonlocal execution_index

            calls["execute_query"] += 1

            action = execution_plan[execution_index]
            execution_index += 1

            if isinstance(action, Exception):
                raise action

            return action

        pipeline.execute_query = fake_execute_query

        caught_exception = None
        result = None

        try:
            result = pipeline.run_query_pipeline(
                "test question"
            )
        except Exception as exc:
            caught_exception = exc

        assert calls["correct_sql"] == expected_corrections, (
            f"expected {expected_corrections} correction calls, "
            f"got {calls['correct_sql']}"
        )

        assert calls["execute_query"] == expected_executions, (
            f"expected {expected_executions} execution attempts, "
            f"got {calls['execute_query']}"
        )

        if expected_exception is None:
            assert caught_exception is None, (
                f"unexpected {type(caught_exception).__name__}: "
                f"{caught_exception}"
            )
            assert result is not None

        else:
            assert isinstance(
                caught_exception,
                expected_exception,
            ), (
                f"expected {expected_exception.__name__}, "
                f"got "
                f"{type(caught_exception).__name__ if caught_exception else 'none'}"
            )

        print(f"✅ PASS: {name}")
        return True

    except Exception as exc:
        print(f"❌ FAIL: {name}")
        print(f"   {type(exc).__name__}: {exc}")
        return False

    finally:
        for key, value in original_functions.items():
            setattr(pipeline, key, value)


def main():
    cases = [
        {
            "name": "valid initial SQL needs no correction",
            "generated_sql": "SELECT 1;",
            "execution_plan": [[(1,)]],
            "expected_corrections": 0,
            "expected_executions": 1,
        },
        {
            "name": "database error is corrected once",
            "generated_sql": 'SELECT "missing" FROM test_db.items;',
            "execution_plan": [
                RuntimeError("column does not exist"),
                [(1,)],
            ],
            "corrected_sql": "SELECT id FROM test_db.items;",
            "expected_corrections": 1,
            "expected_executions": 2,
        },
        {
            "name": "initial unsafe SQL fails closed",
            "generated_sql": "DELETE FROM test_db.items;",
            "execution_plan": [
                UnsafeSQLError(
                    "Unsafe SQL blocked."
                )
            ],
            "expected_exception": UnsafeSQLError,
            "expected_corrections": 0,
            "expected_executions": 1,
        },
        {
            "name": "unsafe corrected SQL is blocked",
            "generated_sql": 'SELECT "missing" FROM test_db.items;',
            "execution_plan": [
                RuntimeError("column does not exist"),
                UnsafeSQLError(
                    "Unsafe SQL blocked."
                ),
            ],
            "corrected_sql": "DELETE FROM test_db.items;",
            "expected_exception": RuntimeError,
            "expected_corrections": 1,
            "expected_executions": 2,
        },
        {
            "name": "failed correction stops after one attempt",
            "generated_sql": 'SELECT "missing" FROM test_db.items;',
            "execution_plan": [
                RuntimeError("column does not exist"),
                RuntimeError("still invalid"),
            ],
            "corrected_sql": 'SELECT "still_missing" FROM test_db.items;',
            "expected_exception": RuntimeError,
            "expected_corrections": 1,
            "expected_executions": 2,
        },
    ]

    passed = 0

    for case in cases:
        if run_case(**case):
            passed += 1

    total = len(cases)

    print()
    print("=" * 60)
    print("PHASE 9.10 SELF-CORRECTION SUITE")
    print("=" * 60)
    print(f"Passed: {passed}/{total}")

    if passed != total:
        raise SystemExit(1)

    print("🎯 All self-correction control-flow tests passed.")


if __name__ == "__main__":
    main()
