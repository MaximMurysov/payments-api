from fastapi.testclient import TestClient
from sqlalchemy import delete, event, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import create_app
from app.models import Tariff
from app.services.tariffs import DEFAULT_TARIFFS, seed_tariffs


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
    # Явные настройки, как в conftest: `.env` разработчика не должен влиять на тест.
    settings = Settings(_env_file=None, webhook_secret=None)

    first = create_app(db_url, settings)
    with TestClient(first):
        pass

    # Проверяем, пока приложение запущено: после выхода lifespan закрывает engine,
    # и новое соединение осталось бы незакрытым.
    second = create_app(db_url, settings)
    with TestClient(second), second.state.session_factory() as db_session:
        assert len(_tariffs(db_session)) == 3


def test_seed_survives_concurrent_seeding(client: TestClient, session: Session) -> None:
    # Два воркера стартуют одновременно: оба увидели пустую таблицу, другой закоммитил раньше.
    session.execute(delete(Tariff))
    session.commit()

    @event.listens_for(session, "before_commit", once=True)
    def _other_worker_seeds_first(_: Session) -> None:
        with client.app.state.session_factory() as other:
            other.add_all(
                Tariff(code=code, title=title, price=price)
                for code, title, price in DEFAULT_TARIFFS
            )
            other.commit()

    seed_tariffs(session)

    assert [t.code for t in _tariffs(session)] == ["basic", "standard", "premium"]
