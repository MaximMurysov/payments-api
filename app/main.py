from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from app import models
from app.config import Settings
from app.db import make_engine
from app.routers import payments as payments_router
from app.routers import tariffs as tariffs_router
from app.services.tariffs import seed_tariffs


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Metadata берём через модуль моделей: его импорт регистрирует в ней все таблицы,
    # и это не зависит от того, какие сервисы импортирует main.
    models.Base.metadata.create_all(app.state.engine)
    with app.state.session_factory() as session:
        seed_tariffs(session)
    yield
    app.state.engine.dispose()


def create_app(database_url: str | None = None, settings: Settings | None = None) -> FastAPI:
    """Собирает приложение.

    Параметры нужны тестам: у каждого теста своя база и свои настройки, независимые от `.env`.
    `database_url`, если задан, важнее `settings.database_url`.
    """
    settings = settings or Settings()
    engine = make_engine(database_url or settings.database_url)

    app = FastAPI(title="Payments API", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = sessionmaker(engine, expire_on_commit=False)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(tariffs_router.router)
    app.include_router(payments_router.router)

    return app


app = create_app()
