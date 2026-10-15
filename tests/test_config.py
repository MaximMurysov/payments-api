import pytest

from app.config import Settings


def test_empty_env_values_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # Именно так выглядит .env, скопированный из .env.example без правок.
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("WEBHOOK_SECRET", "")

    settings = Settings(_env_file=None)

    assert settings.webhook_secret is None
    assert settings.database_url == "sqlite:///./payments.db"


def test_env_values_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./other.db")
    monkeypatch.setenv("WEBHOOK_SECRET", "s3cret")

    settings = Settings(_env_file=None)

    assert settings.database_url == "sqlite:///./other.db"
    assert settings.webhook_secret == "s3cret"
