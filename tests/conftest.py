from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import create_app


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    """Свежее приложение со своей SQLite-базой на каждый тест."""
    app = create_app(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def session(client: TestClient) -> Iterator[Session]:
    """Сессия к той же базе, что и у `client` — для проверок состояния БД."""
    with client.app.state.session_factory() as db_session:
        yield db_session
