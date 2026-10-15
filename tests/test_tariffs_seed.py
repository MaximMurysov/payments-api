from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import Tariff
from app.services.tariffs import seed_tariffs


def _tariffs(session: Session) -> list[Tariff]:
    return list(session.scalars(select(Tariff).order_by(Tariff.id)))


def test_startup_seeds_three_tariffs(client: TestClient, session: Session) -> None:
    tariffs = _tariffs(session)

    assert [(t.code, t.title, t.price) for t in tariffs] == [
        ("basic", "Базовый", 990000),
        ("standard", "Стандарт", 1990000),
        ("premium", "Премиум", 2990000),
    ]
    assert all(type(t.price) is int for t in tariffs)


def test_seed_is_idempotent(client: TestClient, session: Session) -> None:
    seed_tariffs(session)
    seed_tariffs(session)

    assert len(_tariffs(session)) == 3


def test_restart_on_same_database_does_not_duplicate(tmp_path) -> None:
    db_url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"

    for _ in range(2):
        app = create_app(db_url)
        with TestClient(app):
            pass

    with app.state.session_factory() as db_session:
        assert len(_tariffs(db_session)) == 3
