from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime, Dialect, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.db import Base


class PaymentMethod(StrEnum):
    CARD = "card"
    SBP = "sbp"
    INSTALLMENT = "installment"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"


class UTCDateTime(TypeDecorator[datetime]):
    """Дата-время, которое всегда хранится и читается как timezone-aware UTC.

    SQLite не хранит таймзону и отдаёт naive datetime: пишем значение в UTC и при чтении
    помечаем его UTC. Postgres (`timestamptz`) отдаёт aware — приводим его к UTC.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime is not allowed, use datetime.now(UTC)")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def _enum_column_type(enum_cls: type[StrEnum]) -> Enum:
    # В БД пишем значения ("card"), а не имена членов ("CARD"). VARCHAR + CHECK вместо типа ENUM
    # в Postgres: одинаково в SQLite и Postgres, а неизвестное значение отвергает сама БД.
    return Enum(
        enum_cls,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Tariff(Base):
    __tablename__ = "tariffs"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(100))
    # Цена в копейках.
    price: Mapped[int]


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    tariff_id: Mapped[int] = mapped_column(ForeignKey("tariffs.id"))
    email: Mapped[str] = mapped_column(String(320))
    method: Mapped[PaymentMethod] = mapped_column(_enum_column_type(PaymentMethod))
    installment_months: Mapped[int | None]
    # Суммы в копейках: к оплате (цена тарифа минус скидка) и скидка.
    amount: Mapped[int]
    discount: Mapped[int]
    # Нормализованный код промокода (`KVITTO10`) или None, если промокода нет.
    promo_code: Mapped[str | None] = mapped_column(String(32))
    # График рассрочки в копейках; None (SQL NULL, а не JSON 'null') — не рассрочка.
    schedule: Mapped[list[int] | None] = mapped_column(JSON(none_as_null=True))
    status: Mapped[PaymentStatus] = mapped_column(
        _enum_column_type(PaymentStatus), default=PaymentStatus.PENDING
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_utc_now)
