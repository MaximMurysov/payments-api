from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    """Свежее приложение со своей SQLite-базой на каждый тест."""
    # Явные настройки: `.env` и переменные окружения разработчика не должны влиять на тесты.
    settings = Settings(_env_file=None, webhook_secret=None)
    app = create_app(f"sqlite:///{(tmp_path / 'test.db').as_posix()}", settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def session(client: TestClient) -> Iterator[Session]:
    """Сессия к той же базе, что и у `client` — для проверок состояния БД."""
    with client.app.state.session_factory() as db_session:
        yield db_session
