from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Tariff


def test_list_tariffs_returns_seeded_tariffs(client: TestClient, session: Session) -> None:
    response = client.get("/tariffs")

    assert response.status_code == 200
    body = response.json()
    db_tariffs = list(session.scalars(select(Tariff).order_by(Tariff.id)))
    assert body == [{"id": t.id, "title": t.title, "price": t.price} for t in db_tariffs]
    assert [item["price"] for item in body] == [990000, 1990000, 2990000]


def test_list_tariffs_prices_are_int_kopecks(client: TestClient) -> None:
    body = client.get("/tariffs").json()

    # 990000 == 990000.0 в Python, поэтому проверяем именно тип.
    assert all(type(item["price"]) is int for item in body)


def test_list_tariffs_exposes_only_public_fields(client: TestClient) -> None:
    body = client.get("/tariffs").json()

    assert len(body) == 3
    assert all(set(item) == {"id", "title", "price"} for item in body)


def test_list_tariffs_sorted_by_id(client: TestClient) -> None:
    ids = [item["id"] for item in client.get("/tariffs").json()]

    assert ids == sorted(ids)
