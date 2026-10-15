from datetime import timedelta, timezone

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Payment, PaymentMethod, PaymentStatus, Tariff


def _tariff_id(session: Session) -> int:
    tariff_id = session.scalar(select(Tariff.id).where(Tariff.code == "standard"))
    assert tariff_id is not None
    return tariff_id


def _payment(session: Session, **overrides: object) -> Payment:
    fields: dict[str, object] = {
        "tariff_id": _tariff_id(session),
        "email": "student@example.com",
        "method": PaymentMethod.CARD,
        "amount": 1990000,
        "discount": 0,
    }
    fields.update(overrides)
    return Payment(**fields)


def _reload(session: Session, payment_id: int) -> Payment:
    # Сбрасываем кэш сессии, чтобы значения пришли из БД, а не из объекта в памяти.
    session.expire_all()
    payment = session.get(Payment, payment_id)
    assert payment is not None
    return payment


def test_payment_defaults_after_reload(session: Session) -> None:
    payment = _payment(session)
    session.add(payment)
    session.commit()

    stored = _reload(session, payment.id)

    assert stored.status is PaymentStatus.PENDING
    assert stored.promo_code is None
    assert stored.schedule is None
    assert stored.installment_months is None
    assert stored.idempotency_key is None


def test_created_at_is_timezone_aware_utc_after_reload(session: Session) -> None:
    payment = _payment(session)
    session.add(payment)
    session.commit()

    stored = _reload(session, payment.id)

    # SQLite не хранит таймзону: без своего типа колонки отсюда пришёл бы naive datetime.
    assert stored.created_at.tzinfo is not None
    assert stored.created_at.utcoffset() == timedelta(0)


def test_created_at_non_utc_value_is_stored_as_utc(session: Session) -> None:
    payment = _payment(session)
    session.add(payment)
    session.commit()
    plus_three = payment.created_at.astimezone(timezone(timedelta(hours=3)))
    payment.created_at = plus_three
    session.commit()

    stored = _reload(session, payment.id)

    assert stored.created_at == plus_three
    assert stored.created_at.utcoffset() == timedelta(0)


def test_enums_are_stored_as_values(session: Session) -> None:
    session.add(_payment(session, method=PaymentMethod.INSTALLMENT, installment_months=3))
    session.commit()

    row = session.execute(text("SELECT method, status FROM payments")).one()

    assert tuple(row) == ("installment", "pending")


def test_status_column_rejects_unknown_value(session: Session) -> None:
    payment = _payment(session)
    session.add(payment)
    session.commit()

    with pytest.raises(IntegrityError):
        session.execute(
            text("UPDATE payments SET status = 'bogus' WHERE id = :id"), {"id": payment.id}
        )
    session.rollback()


def test_schedule_round_trips_as_int_list(session: Session) -> None:
    schedule = [663334, 663333, 663333]
    payment = _payment(
        session, method=PaymentMethod.INSTALLMENT, installment_months=3, schedule=schedule
    )
    session.add(payment)
    session.commit()

    stored = _reload(session, payment.id)

    assert stored.schedule == schedule
    assert all(type(part) is int for part in stored.schedule)


def test_missing_schedule_is_sql_null(session: Session) -> None:
    # Явный None, как его передаст сервис для оплаты картой или СБП.
    session.add(_payment(session, schedule=None))
    session.commit()

    # JSON-колонка по умолчанию сохраняет явный None как JSON 'null', а не как SQL NULL.
    null_count = session.scalar(text("SELECT count(*) FROM payments WHERE schedule IS NULL"))

    assert null_count == 1


def test_payment_requires_existing_tariff(session: Session) -> None:
    session.add(_payment(session, tariff_id=999999))

    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    assert session.scalar(select(func.count()).select_from(Payment)) == 0


def test_idempotency_key_is_unique(session: Session) -> None:
    session.add(_payment(session, idempotency_key="key-1"))
    session.commit()
    session.add(_payment(session, idempotency_key="key-1"))

    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    assert session.scalar(select(func.count()).select_from(Payment)) == 1


def test_many_payments_without_idempotency_key_are_allowed(session: Session) -> None:
    session.add_all([_payment(session), _payment(session)])
    session.commit()

    assert session.scalar(select(func.count()).select_from(Payment)) == 2


def test_enum_check_constraints_are_named_after_columns(session: Session) -> None:
    # Имя по классу enum (`paymentstatus`) не говорит, какую колонку оно защищает, и даст
    # конфликт имён в Postgres, если один enum понадобится в двух колонках.
    constraints = inspect(session.get_bind()).get_check_constraints("payments")

    names = {constraint["name"] for constraint in constraints}

    assert {"ck_payments_method", "ck_payments_status"} <= names
