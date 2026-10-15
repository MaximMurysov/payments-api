from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Tariff
from app.schemas import TariffOut
from app.services.tariffs import list_tariffs

router = APIRouter(tags=["tariffs"])


@router.get("/tariffs", response_model=list[TariffOut])
def get_tariffs(session: Annotated[Session, Depends(get_session)]) -> list[Tariff]:
    return list_tariffs(session)
