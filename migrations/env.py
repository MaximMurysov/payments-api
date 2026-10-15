from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, make_url, pool

from app import models
from app.config import Settings

config = context.config

if config.config_file_name is not None:
    # Не глушим логгеры, созданные до миграций (uvicorn, приложение, pytest).
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Импорт `app.models` регистрирует в metadata все таблицы — по ней работает autogenerate.
target_metadata = models.Base.metadata


def _database_url() -> str:
    # Явный `sqlalchemy.url` (так делают тесты) важнее настроек приложения.
    return config.get_main_option("sqlalchemy.url") or Settings().database_url


def _render_as_batch(url: str) -> bool:
    # SQLite почти не умеет ALTER TABLE: batch-режим пересоздаёт таблицу целиком.
    return make_url(url).get_backend_name() == "sqlite"


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`: печатает SQL, не подключаясь к базе."""
    url = _database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=_render_as_batch(url),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _database_url()
    engine = create_engine(url, poolclass=pool.NullPool)

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=_render_as_batch(url),
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
