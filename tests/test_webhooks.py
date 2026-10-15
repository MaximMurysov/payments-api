from itertools import product

import pytest

from app.models import PaymentStatus
from app.services.payments import can_transition

ALLOWED_PAIRS = {
    (PaymentStatus.PENDING, PaymentStatus.SUCCEEDED),
    (PaymentStatus.PENDING, PaymentStatus.FAILED),
    (PaymentStatus.SUCCEEDED, PaymentStatus.REFUNDED),
}


@pytest.mark.parametrize(
    ("old", "new"),
    list(product(PaymentStatus, PaymentStatus)),
    ids=lambda status: status.value,
)
def test_can_transition_matches_allowed_table(old: PaymentStatus, new: PaymentStatus) -> None:
    assert can_transition(old, new) is ((old, new) in ALLOWED_PAIRS)


def test_exactly_three_transitions_are_allowed() -> None:
    pairs = list(product(PaymentStatus, PaymentStatus))

    assert len(pairs) == 16
    assert sum(can_transition(old, new) for old, new in pairs) == 3
