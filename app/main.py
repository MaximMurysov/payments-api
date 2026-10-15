import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db import make_engine
from app.errors import InvalidTransition, PaymentNotFound, TariffNotFound, UnknownPromoCode
from app.routers import payments as payments_router
from app.routers import tariffs as tariffs_router
from app.routers import webhooks as webhooks_router
from app.services.tariffs import seed_tariffs

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Таблицы создают миграции (`alembic upgrade head`), а не приложение: схема в одном месте.
    with app.state.session_factory() as session:
        seed_tariffs(session)
    yield
    app.state.engine.dispose()


def _detail(status_code: int, message: str) -> JSONResponse:
    # Доменная ошибка в формате HTTPException FastAPI: {"detail": "..."}.
    return JSONResponse(status_code=status_code, content={"detail": message})


def _add_exception_handlers(app: FastAPI) -> None:
    """Сервисы бросают доменные исключения из `app.errors`; HTTP-коды им назначаются здесь."""

    @app.exception_handler(UnknownPromoCode)
    async def unknown_promo_code(request: Request, exc: UnknownPromoCode) -> JSONResponse:
        # `exc.code`, а не `str(exc)`: там Python-repr для логов (`'NOPE'`).
        return _detail(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown promo code: {exc.code}")

    @app.exception_handler(TariffNotFound)
    async def tariff_not_found(request: Request, exc: TariffNotFound) -> JSONResponse:
        return _detail(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Tariff {exc.tariff_id} not found")

    @app.exception_handler(PaymentNotFound)
    async def payment_not_found(request: Request, exc: PaymentNotFound) -> JSONResponse:
        return _detail(status.HTTP_404_NOT_FOUND, f"Payment {exc.payment_id} not found")

    @app.exception_handler(InvalidTransition)
    async def invalid_transition(request: Request, exc: InvalidTransition) -> JSONResponse:
        # Чтобы отказ банку было видно в логах сервера. Только поля платежа: тело и заголовки
        # запроса (подпись) не логируются.
        logger.warning(
            "invalid status transition: payment_id=%s %s -> %s",
            exc.payment_id,
            exc.old.value,
            exc.new.value,
        )
        # Формат 409 задан ТЗ буквально: не `{"detail": ...}`, поэтому не HTTPException.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT, content={"error": "invalid_transition"}
        )


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

    _add_exception_handlers(app)
    app.include_router(tariffs_router.router)
    app.include_router(payments_router.router)
    app.include_router(webhooks_router.router)

    return app


app = create_app()
