from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    # SQLite по умолчанию запрещает использовать соединение из другого потока,
    # а FastAPI выполняет синхронные обработчики в пуле потоков.
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


def get_session(request: Request) -> Iterator[Session]:
    """Сессия на один запрос; фабрику берём из приложения, а не из глобальной переменной."""
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session
