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
        # Другой воркер заполнил таблицу между проверкой и вставкой: UNIQUE(code) не дал
        # создать дубли, а наш commit откатываем и считаем работу выполненной.
        session.rollback()
