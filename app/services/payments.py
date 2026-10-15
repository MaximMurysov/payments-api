from sqlalchemy.orm import Session

from app.errors import TariffNotFound
from app.models import Payment, Tariff
from app.schemas import PaymentCreate
from app.services.pricing import build_schedule, calc_discount, normalize_promo_code, resolve_promo


def create_payment(session: Session, data: PaymentCreate) -> Payment:
    """Создаёт платёж: цена тарифа → скидка по промокоду → сумма к оплате → график рассрочки.

    Цена берётся только из таблицы тарифов, не от клиента: поэтому `amount >= 0`.
    Несуществующий тариф — `TariffNotFound`, неизвестный промокод — `UnknownPromoCode`.
    """
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
    )
    session.add(payment)
    session.commit()
    return payment
