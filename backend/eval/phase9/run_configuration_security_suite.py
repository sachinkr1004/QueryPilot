import os
import subprocess
import sys
from pathlib import Path

import config
import db
from llm import baseline_client as bc


BACKEND_DIR = Path(__file__).resolve().parents[2]


def run_test(name, test):
    try:
        test()
        print(f"✅ PASS: {name}")
        return True
    except AssertionError as error:
        print(f"❌ FAIL: {name}")
        print(f"   {error}")
        return False


def test_valid_config():
    required = [
        config.GROQ_API_KEY,
        config.DB_NAME,
        config.DB_USER,
        config.DB_PASSWORD,
        config.DB_HOST,
        config.DB_PORT,
    ]
    assert all(value and value.strip() for value in required)


def test_missing_groq_key():
    env = os.environ.copy()
    env.pop("GROQ_API_KEY", None)
    env["PYTHONPATH"] = str(BACKEND_DIR)

    result = subprocess.run(
        [sys.executable, "-c", "import config"],
        cwd="/tmp",
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "ConfigurationError" in result.stderr
    assert "GROQ_API_KEY" in result.stderr
    assert "gsk_" not in result.stderr


def test_missing_db_name():
    env = os.environ.copy()
    env.update(
        {
            "GROQ_API_KEY": "test_key",
            "DB_USER": "test_user",
            "DB_PASSWORD": "test_password",
            "DB_HOST": "localhost",
            "DB_PORT": "5432",
            "PYTHONPATH": str(BACKEND_DIR),
        }
    )
    env.pop("DB_NAME", None)

    result = subprocess.run(
        [sys.executable, "-c", "import config"],
        cwd="/tmp",
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "ConfigurationError" in result.stderr
    assert "DB_NAME" in result.stderr
    assert "test_password" not in result.stderr


def test_git_secret_protection():
    env_check = subprocess.run(
        ["git", "check-ignore", "-q", ".env"],
        cwd=BACKEND_DIR,
    )
    example_check = subprocess.run(
        ["git", "check-ignore", "-q", ".env.example"],
        cwd=BACKEND_DIR,
    )

    assert env_check.returncode == 0
    assert example_check.returncode != 0


def test_env_example_safe():
    text = (BACKEND_DIR / ".env.example").read_text()

    required_names = [
        "GROQ_API_KEY=",
        "DB_NAME=",
        "DB_USER=",
        "DB_PASSWORD=",
        "DB_HOST=",
        "DB_PORT=",
    ]

    assert all(name in text for name in required_names)
    assert "gsk_" not in text
    assert config.GROQ_API_KEY not in text
    assert config.DB_PASSWORD not in text


def test_consumers_are_centralized():
    db_text = (BACKEND_DIR / "db.py").read_text()
    client_text = (
        BACKEND_DIR / "llm" / "baseline_client.py"
    ).read_text()

    for text in (db_text, client_text):
        assert "os.getenv" not in text
        assert "os.environ" not in text
        assert "load_dotenv" not in text

    assert "from config import" in db_text
    assert "from config import GROQ_API_KEY" in client_text


def test_db_configuration_wiring():
    original_connect = db.psycopg2.connect
    captured = {}

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return object()

    db.psycopg2.connect = fake_connect

    try:
        db.get_connection()
    finally:
        db.psycopg2.connect = original_connect

    assert captured == {
        "dbname": config.DB_NAME,
        "user": config.DB_USER,
        "password": config.DB_PASSWORD,
        "host": config.DB_HOST,
        "port": config.DB_PORT,
    }


def test_frozen_groq_policy():
    assert bc.client.max_retries == 2

    timeout = bc.client.timeout
    assert timeout.connect == 5.0
    assert timeout.read == 60.0
    assert timeout.write == 60.0
    assert timeout.pool == 60.0


def main():
    tests = [
        ("required configuration loaded", test_valid_config),
        ("missing GROQ key fails safely", test_missing_groq_key),
        ("missing DB_NAME fails safely", test_missing_db_name),
        ("Git secret protection", test_git_secret_protection),
        ("safe .env.example", test_env_example_safe),
        ("configuration consumers centralized", test_consumers_are_centralized),
        ("database configuration wiring", test_db_configuration_wiring),
        ("frozen Groq reliability policy", test_frozen_groq_policy),
    ]

    passed = sum(run_test(name, test) for name, test in tests)

    print()
    print("=" * 60)
    print("PHASE 9.15 CONFIGURATION + SECURITY SUITE")
    print("=" * 60)
    print(f"Passed: {passed}/{len(tests)}")

    if passed != len(tests):
        raise SystemExit(1)

    print("🎯 All Phase 9.15 configuration/security tests passed.")


if __name__ == "__main__":
    main()
