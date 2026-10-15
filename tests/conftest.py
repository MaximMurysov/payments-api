from collections.abc import Callable, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import models
from app.config import Settings
from app.main import create_app


@pytest.fixture
def make_app() -> Callable[..., FastAPI]:
    """`create_app` + таблицы в базе: приложение их не создаёт, это делают миграции.

    Тестам хватает `create_all` по моделям; что миграции дают ту же схему, проверяет
    `test_migrations.py`.
    """

    def _make_app(database_url: str, settings: Settings | None = None) -> FastAPI:
        app = create_app(database_url, settings)
        models.Base.metadata.create_all(app.state.engine)
        return app

    return _make_app


@pytest.fixture
def client(tmp_path, make_app: Callable[..., FastAPI]) -> Iterator[TestClient]:
    """Свежее приложение со своей SQLite-базой на каждый тест."""
    # Явные настройки: `.env` и переменные окружения разработчика не должны влиять на тесты.
    settings = Settings(_env_file=None, webhook_secret=None)
    app = make_app(f"sqlite:///{(tmp_path / 'test.db').as_posix()}", settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def session(client: TestClient) -> Iterator[Session]:
    """Сессия к той же базе, что и у `client` — для проверок состояния БД."""
    with client.app.state.session_factory() as db_session:
        yield db_session
