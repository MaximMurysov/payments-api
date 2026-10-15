from pathlib import Path
from typing import Any

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, inspect, select

from app import models
from app.config import Settings
from app.main import create_app

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def _alembic_config(db_url: str) -> Config:
    config = Config(ALEMBIC_INI)
    # `%` в значениях ini — синтаксис интерполяции configparser, его нужно экранировать.
    config.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))
    return config


def _db_url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"


def test_migrations_match_models(tmp_path: Path) -> None:
    # Модель поменяли, а миграцию не добавили — тест покажет расхождение.
    db_url = _db_url(tmp_path)

    command.upgrade(_alembic_config(db_url), "head")

    engine = create_engine(db_url)
    try:
        with engine.connect() as connection:
            diff = compare_metadata(MigrationContext.configure(connection), models.Base.metadata)
    finally:
        engine.dispose()
    assert diff == []


def test_migrations_create_same_check_constraints_as_models(tmp_path: Path) -> None:
    # `compare_metadata` не сравнивает CHECK, а на них держится допустимость `method` и `status`.
    migrated_url = _db_url(tmp_path)
    command.upgrade(_alembic_config(migrated_url), "head")
    models_engine = create_engine(f"sqlite:///{(tmp_path / 'models.db').as_posix()}")
    models.Base.metadata.create_all(models_engine)
    migrated_engine = create_engine(migrated_url)

    def checks(engine: Engine) -> dict[str, list[dict[str, Any]]]:
        inspector = inspect(engine)
        return {
            table: sorted(inspector.get_check_constraints(table), key=lambda c: c["name"])
            for table in models.Base.metadata.tables
        }

    try:
        assert checks(migrated_engine) == checks(models_engine)
        assert {c["name"] for c in checks(migrated_engine)["payments"]} == {
            "ck_payments_method",
            "ck_payments_status",
        }
    finally:
        models_engine.dispose()
        migrated_engine.dispose()


def test_downgrade_removes_all_tables(tmp_path: Path) -> None:
    db_url = _db_url(tmp_path)
    config = _alembic_config(db_url)

    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = create_engine(db_url)
    try:
        assert inspect(engine).get_table_names() == ["alembic_version"]
    finally:
        engine.dispose()


def test_app_seeds_tariffs_on_migrated_database(tmp_path: Path) -> None:
    db_url = _db_url(tmp_path)
    command.upgrade(_alembic_config(db_url), "head")

    app = create_app(db_url, Settings(_env_file=None, webhook_secret=None))
    with TestClient(app), app.state.session_factory() as db_session:
        codes = db_session.scalars(select(models.Tariff.code).order_by(models.Tariff.id)).all()

    assert codes == ["basic", "standard", "premium"]
