import os

from dotenv import load_dotenv


load_dotenv()


class ConfigurationError(RuntimeError):
    """Raised when required application configuration is missing."""

    pass


def _require_env(name: str) -> str:
    value = os.getenv(name)

    if value is None or not value.strip():
        raise ConfigurationError(
            f"Missing required environment variable: {name}"
        )

    return value


GROQ_API_KEY = _require_env("GROQ_API_KEY")

DB_NAME = _require_env("DB_NAME")
DB_USER = _require_env("DB_USER")
DB_PASSWORD = _require_env("DB_PASSWORD")
DB_HOST = _require_env("DB_HOST")
DB_PORT = _require_env("DB_PORT")
