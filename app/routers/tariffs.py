from fastapi import APIRouter

from app.db import SessionDep
from app.models import Tariff
from app.schemas import TariffOut
from app.services.tariffs import list_tariffs

router = APIRouter(tags=["tariffs"])


@router.get("/tariffs", response_model=list[TariffOut])
def get_tariffs(session: SessionDep) -> list[Tariff]:
    return list_tariffs(session)
