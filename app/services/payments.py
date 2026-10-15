from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import PaymentNotFound, TariffNotFound
from app.models import Payment, Tariff
from app.schemas import PaymentCreate
from app.services.pricing import build_schedule, calc_discount, normalize_promo_code, resolve_promo


def create_payment(
    session: Session, data: PaymentCreate, idempotency_key: str | None = None
) -> tuple[Payment, bool]:
    """Создаёт платёж: цена тарифа → скидка по промокоду → сумма к оплате → график рассрочки.

    Возвращает `(платёж, created)`. Если передан `idempotency_key` и платёж с таким ключом уже есть,
    возвращает его с `created=False`, ничего не создавая: тело повторного запроса не сравнивается
    и не проверяется (осознанное решение; в продакшене стоило бы сверять хеш тела).

    Цена берётся только из таблицы тарифов, не от клиента: поэтому `amount >= 0`.
    Несуществующий тариф — `TariffNotFound`, неизвестный промокод — `UnknownPromoCode`.
    """
    if idempotency_key is not None:
        existing = session.scalar(select(Payment).where(Payment.idempotency_key == idempotency_key))
        if existing is not None:
            return existing, False

    tariff = session.get(Tariff, data.tariff_id)
    if tariff is None:
        raise TariffNotFound(data.tariff_id)

    discount = calc_discount(tariff.price, resolve_promo(data.promo_code))
    amount = tariff.price - discount
    # Схема гарантирует: срок задан только у рассрочки.
    schedule = (
        build_schedule(amount, data.installment_months)
        if data.installment_months is not None
        else None
    )

    payment = Payment(
        tariff_id=tariff.id,
        email=str(data.email),
        method=data.method,
        installment_months=data.installment_months,
        amount=amount,
        discount=discount,
        promo_code=normalize_promo_code(data.promo_code),
        schedule=schedule,
        idempotency_key=idempotency_key,
    )
    session.add(payment)
    session.commit()
    return payment, True


def get_payment(session: Session, payment_id: int) -> Payment:
    payment = session.get(Payment, payment_id)
    if payment is None:
        raise PaymentNotFound(payment_id)
    return payment
