"""Phase 9.11 deterministic LLM client reliability regression suite."""

from types import SimpleNamespace

import groq
import httpx

from llm import baseline_client as bc


def make_response(
    content="SELECT 1;",
    choices=True,
    finish_reason="stop",
    completion_tokens=10,
    reasoning_tokens=0,
):
    if not choices:
        return SimpleNamespace(choices=[])

    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ],
        usage=SimpleNamespace(
            completion_tokens=completion_tokens,
            completion_tokens_details=SimpleNamespace(
                reasoning_tokens=reasoning_tokens
            ),
        ),
    )


def run_case(name, func, fake_create, expected=None, expected_exception=None):
    original_create = bc.client.chat.completions.create

    try:
        bc.client.chat.completions.create = fake_create

        caught = None
        result = None

        try:
            result = func()
        except Exception as exc:
            caught = exc

        if expected_exception is None:
            assert caught is None, (
                f"unexpected {type(caught).__name__}: {caught}"
            )
            assert result == expected, (
                f"expected {expected!r}, got {result!r}"
            )
        else:
            assert isinstance(caught, expected_exception), (
                f"expected {expected_exception.__name__}, got "
                f"{type(caught).__name__ if caught else 'none'}"
            )

        print(f"✅ PASS: {name}")
        return True

    except Exception as exc:
        print(f"❌ FAIL: {name}")
        print(f"   {type(exc).__name__}: {exc}")
        return False

    finally:
        bc.client.chat.completions.create = original_create


def generate():
    return bc.generate_sql(
        "test question",
        "Table: test.items\nColumns:\n- id: integer",
        [],
    )


def correct():
    return bc.correct_sql(
        "test question",
        "Table: test.items\nColumns:\n- id: integer",
        "SELECT bad FROM test.items;",
        'column "bad" does not exist',
        [],
    )


def review():
    return bc.review_sql_semantics(
        "test question",
        "Table: test.items\nColumns:\n- id: integer",
        "SELECT id FROM test.items;",
        [],
    )


def main():
    request = httpx.Request(
        "POST",
        "https://api.groq.com/openai/v1/chat/completions",
    )

    def http_response(status_code):
        return httpx.Response(
            status_code,
            request=request,
        )

    provider_errors = [
        groq.APIConnectionError(
            message="connection failed",
            request=request,
        ),
        groq.APITimeoutError(request),
        groq.RateLimitError(
            "rate limited",
            response=http_response(429),
            body=None,
        ),
        groq.InternalServerError(
            "server error",
            response=http_response(500),
            body=None,
        ),
        groq.BadRequestError(
            "bad request",
            response=http_response(400),
            body=None,
        ),
        groq.AuthenticationError(
            "authentication failed",
            response=http_response(401),
            body=None,
        ),
    ]

    cases = [
        (
            "generation valid response",
            generate,
            lambda *a, **k: make_response("SELECT 1;"),
            "SELECT 1;",
            None,
        ),
        (
            "generation empty choices",
            generate,
            lambda *a, **k: make_response(choices=False),
            None,
            bc.LLMResponseError,
        ),
        (
            "generation none content",
            generate,
            lambda *a, **k: make_response(None),
            None,
            bc.LLMResponseError,
        ),
        (
            "generation empty content",
            generate,
            lambda *a, **k: make_response(""),
            None,
            bc.LLMResponseError,
        ),
        (
            "generation whitespace content",
            generate,
            lambda *a, **k: make_response("   \n\t"),
            None,
            bc.LLMResponseError,
        ),
        (
            "correction valid response",
            correct,
            lambda *a, **k: make_response(
                "SELECT id FROM test.items;"
            ),
            "SELECT id FROM test.items;",
            None,
        ),
        (
            "correction empty response",
            correct,
            lambda *a, **k: make_response(""),
            None,
            bc.LLMResponseError,
        ),
        (
            "review KEEP response",
            review,
            lambda *a, **k: make_response("KEEP"),
            "SELECT id FROM test.items;",
            None,
        ),
        (
            "review empty response",
            review,
            lambda *a, **k: make_response(""),
            None,
            bc.LLMResponseError,
        ),
    ]

    for error in provider_errors:
        def raise_error(*args, _error=error, **kwargs):
            raise _error

        cases.append(
            (
                f"{type(error).__name__} propagates unchanged",
                generate,
                raise_error,
                None,
                type(error),
            )
        )

    passed = 0

    for name, func, fake_create, expected, expected_exception in cases:
        if run_case(
            name,
            func,
            fake_create,
            expected,
            expected_exception,
        ):
            passed += 1

    # Verify per-operation completion-token ceilings.
    token_policy_cases = [
        ("generation token ceiling == 2000", generate, 2000),
        ("correction token ceiling == 1000", correct, 1000),
        ("semantic review token ceiling == 1000", review, 1000),
    ]

    for name, func, expected_tokens in token_policy_cases:
        original_create = bc.client.chat.completions.create
        captured = {}

        def capture_create(*args, **kwargs):
            captured.update(kwargs)

            content = (
                "KEEP"
                if func is review
                else "SELECT id FROM test.items;"
            )

            return make_response(content)

        try:
            bc.client.chat.completions.create = capture_create
            func()

            assert (
                captured.get("max_completion_tokens")
                == expected_tokens
            ), (
                f"expected {expected_tokens}, got "
                f"{captured.get('max_completion_tokens')}"
            )

            print(f"✅ PASS: {name}")
            passed += 1

        finally:
            bc.client.chat.completions.create = original_create

    # Verify malformed-response diagnostics without logging reasoning text.
    try:
        bc.extract_response_text(
            make_response(
                "",
                finish_reason="length",
                completion_tokens=1000,
                reasoning_tokens=1000,
            )
        )
        diagnostic_passed = False
    except bc.LLMResponseError as exc:
        message = str(exc)
        diagnostic_passed = (
            "finish_reason='length'" in message
            and "completion_tokens=1000" in message
            and "reasoning_tokens=1000" in message
        )

    if diagnostic_passed:
        print("✅ PASS: malformed response diagnostic metadata")
        passed += 1
    else:
        print("❌ FAIL: malformed response diagnostic metadata")

    print()
    print("=" * 60)
    print("PHASE 9.11 LLM RELIABILITY SUITE")
    print("=" * 60)

    # Verify frozen Groq client policy.
    assert bc.client.max_retries == 2
    print("✅ PASS: Groq max_retries == 2")

    timeout = bc.client.timeout
    assert timeout.connect == 5.0
    assert timeout.read == 60.0
    assert timeout.write == 60.0
    assert timeout.pool == 60.0
    print("✅ PASS: Groq timeout policy frozen")

    passed += 2
    total = len(cases) + 6

    print(f"Passed: {passed}/{total}")

    if passed != total:
        raise SystemExit(1)

    print("🎯 All Phase 9.11 reliability tests passed.")


if __name__ == "__main__":
    main()
