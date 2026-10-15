from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Tariff

# (code, title, price в копейках)
DEFAULT_TARIFFS: tuple[tuple[str, str, int], ...] = (
    ("basic", "Базовый", 990000),
    ("standard", "Стандарт", 1990000),
    ("premium", "Премиум", 2990000),
)


def seed_tariffs(session: Session) -> None:
    """Заполняет таблицу тарифов, только если она пустая: повторный старт не плодит дубли."""
    if session.scalar(select(Tariff.id).limit(1)) is not None:
        return
    session.add_all(
        Tariff(code=code, title=title, price=price) for code, title, price in DEFAULT_TARIFFS
    )
    try:
        session.commit()
    except IntegrityError:
        # Наш commit откатываем. Если тарифы уже есть, их вставил другой воркер между проверкой
        # и вставкой (UNIQUE(code) не дал создать дубли) — работа выполнена. Если тарифов нет,
        # это не гонка, а ошибка в данных: глотать её нельзя, иначе приложение молча стартует
        # с пустой таблицей.
        session.rollback()
        if session.scalar(select(Tariff.id).limit(1)) is None:
            raise


def list_tariffs(session: Session) -> list[Tariff]:
    return list(session.scalars(select(Tariff).order_by(Tariff.id)))
