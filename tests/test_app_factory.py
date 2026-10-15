from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import create_app


def test_injected_settings_are_used(tmp_path) -> None:
    db_url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    settings = Settings(_env_file=None, webhook_secret="s3cret")

    app = create_app(db_url, settings)

    assert app.state.settings.webhook_secret == "s3cret"


def test_database_url_argument_overrides_settings(tmp_path) -> None:
    settings = Settings(_env_file=None, database_url="sqlite:///./from-settings.db")
    db_url = f"sqlite:///{(tmp_path / 'explicit.db').as_posix()}"

    app = create_app(db_url, settings)

    assert app.state.engine.url.database.endswith("explicit.db")


def test_client_fixture_ignores_developer_env(client: TestClient) -> None:
    # Фикстура задаёт настройки явно: секрет из .env и окружения в тесты не попадает.
    assert client.app.state.settings.webhook_secret is None


def test_session_fixture_uses_test_database(session: Session, tmp_path) -> None:
    assert session.execute(text("select 1")).scalar() == 1
    assert (tmp_path / "test.db").exists()


def test_apps_do_not_share_database(tmp_path, make_app: Callable[..., FastAPI]) -> None:
    first = make_app(f"sqlite:///{(tmp_path / 'a.db').as_posix()}")
    second = make_app(f"sqlite:///{(tmp_path / 'b.db').as_posix()}")

    with TestClient(first), TestClient(second):
        with first.state.session_factory() as db_session:
            db_session.execute(text("create table marker (id integer)"))
            db_session.commit()

        assert inspect(first.state.engine).has_table("marker")
        assert not inspect(second.state.engine).has_table("marker")
