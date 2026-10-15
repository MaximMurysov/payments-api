import hashlib
import hmac

from fastapi import HTTPException, Request, status


async def verify_signature(request: Request) -> None:
    """Проверяет `X-Signature` вебхука: HMAC-SHA256 от сырых байтов тела, hex в нижнем регистре.

    Без `WEBHOOK_SECRET` проверка выключена. Подпись считается от байтов, как они пришли:
    пересериализованный JSON дал бы другой дайджест.
    """
    secret = request.app.state.settings.webhook_secret
    if secret is None:
        return

    received = request.headers.get("X-Signature")
    if received is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing signature")

    expected = hmac.new(secret.encode(), await request.body(), hashlib.sha256).hexdigest()
    # Сравниваем байты: `compare_digest` на `str` с не-ASCII символами бросает TypeError (500).
    if not hmac.compare_digest(received.encode(), expected.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid signature")
