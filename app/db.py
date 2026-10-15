from collections.abc import Iterator
from typing import Any

from fastapi import Request
from sqlalchemy import Engine, create_engine, event, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    # SQLite по умолчанию запрещает использовать соединение из другого потока,
    # а FastAPI выполняет синхронные обработчики в пуле потоков.
    is_sqlite = make_url(url).get_backend_name() == "sqlite"
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine = create_engine(url, connect_args=connect_args)
    if is_sqlite:
        # SQLite проверяет внешние ключи, только если это включено на каждом соединении.
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def _enable_sqlite_foreign_keys(dbapi_connection: Any, connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_session(request: Request) -> Iterator[Session]:
    """Сессия на один запрос; фабрику берём из приложения, а не из глобальной переменной."""
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session
