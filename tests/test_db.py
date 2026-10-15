from sqlalchemy import text
from sqlalchemy.orm import Session


def test_sqlite_enforces_foreign_keys(session: Session) -> None:
    # SQLite по умолчанию не проверяет внешние ключи: без PRAGMA `tariff_id`
    # мог бы ссылаться на несуществующий тариф.
    assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1
