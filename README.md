# Payments API

Сервис приёма оплаты курсов для онлайн-школы: тарифы, создание платежа с промокодом и рассрочкой,
защита от повторных запросов через `Idempotency-Key` и вебхук банка, который меняет статус платежа.

Реализация тестового задания (далее — ТЗ).

Стек: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.x (синхронно), SQLite по умолчанию, pytest + httpx, ruff.

## Требования

- Python 3.11 или новее (проверено на 3.14; CI запускает тесты на 3.11 и 3.14).

## Установка и запуск

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

Если `.venv\Scripts\activate` не запускается с сообщением «running scripts is disabled», разрешите
выполнение скриптов для текущего пользователя: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
Либо не активируйте окружение и вызывайте его Python напрямую: `.venv\Scripts\python.exe -m pip install -r requirements-dev.txt`
и `.venv\Scripts\python.exe -m uvicorn app.main:app --reload`.

Linux / macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

После запуска Swagger доступен на <http://127.0.0.1:8000/docs>.

Настройки читаются из переменных окружения и из файла `.env` в папке запуска. Шаблон: `.env.example`
(скопировать в `.env`, это необязательно: без `.env` работают значения по умолчанию).

| Переменная       | По умолчанию              | Смысл                                                                       |
| ---------------- | ------------------------- | --------------------------------------------------------------------------- |
| `DATABASE_URL`   | `sqlite:///./payments.db` | Строка подключения к БД; путь к SQLite относительный (файл в папке запуска) |
| `WEBHOOK_SECRET` | пусто                     | Секрет подписи вебхука; пока не используется, см. «Принятые решения»        |

## Тесты и линтер

```bash
pytest                       # все тесты (Windows и Linux/macOS одинаково)
pytest tests/test_pricing.py -k schedule -v   # выборочно
ruff check .                 # линт
ruff format --check .        # проверка форматирования
```

Каждый тест работает со своей свежей SQLite во временной папке и не трогает `payments.db`.

При прогоне pytest (pytest 9.1.1, httpx 0.28.1) выводится предупреждение `StarletteDeprecationWarning`
про `httpx2`: оно относится к `TestClient`. ТЗ требует `httpx`, поэтому пакет оставлен как есть.

## Примеры запросов (curl)

Ответы ниже получены на запущенном сервере; суммы в копейках.

Примеры рассчитаны на **пустую базу**: id 1 и 2 и ключ `demo-key-1` работают только на свежем
`payments.db`. Если вы уже запускали сервер и делали запросы, остановите его (Ctrl+C), удалите файл
(`rm payments.db` в bash, `Remove-Item payments.db` в PowerShell) и запустите сервер снова. Удалять файл
при работающем сервере нельзя: на Windows он занят, а на Linux сервер потеряет таблицы (они создаются
только при старте) и будет отвечать 500.

Команды записаны в синтаксисе bash: в Git Bash они запускаются как есть. В Windows PowerShell 5.1 `curl` —
алиас `Invoke-WebRequest`, и команды не работают как есть. Там используйте `curl.exe`, а кавычки внутри JSON
могут потребовать экранирования. Проще всего Git Bash.

Тарифы: `basic` — 990000, `standard` — 1990000, `premium` — 2990000 (id 1, 2, 3).

**Список тарифов**

```bash
curl -s http://127.0.0.1:8000/tariffs
```

```json
[{"id":1,"title":"Базовый","price":990000},{"id":2,"title":"Стандарт","price":1990000},{"id":3,"title":"Премиум","price":2990000}]
```

**Оплата картой с промокодом** (регистр и пробелы по краям не важны) → `201`

```bash
curl -s -X POST http://127.0.0.1:8000/payments \
  -H "Content-Type: application/json" \
  -d '{"tariff_id":1,"email":"a@example.com","method":"card","promo_code":" kvitto10 "}'
```

```json
{"id":1,"status":"pending","tariff_id":1,"amount":891000,"discount":99000,"method":"card","installment_months":null,"schedule":null,"email":"a@example.com","created_at":"2026-10-15T15:03:08.419995Z"}
```

**Рассрочка на 3 месяца с `Idempotency-Key`** → `201`

```bash
curl -s -X POST http://127.0.0.1:8000/payments \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-key-1" \
  -d '{"tariff_id":2,"email":"b@example.com","method":"installment","installment_months":3}'
```

```json
{"id":2,"status":"pending","tariff_id":2,"amount":1990000,"discount":0,"method":"installment","installment_months":3,"schedule":[663334,663333,663333],"email":"b@example.com","created_at":"2026-10-15T15:03:08.470513Z"}
```

**Повтор того же запроса с тем же ключом** → `200`, возвращается уже созданный платёж, второй не создаётся

```bash
curl -s -X POST http://127.0.0.1:8000/payments \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-key-1" \
  -d '{"tariff_id":2,"email":"b@example.com","method":"installment","installment_months":3}'
```

**Получение платежа** → `200` или `404`

```bash
curl -s http://127.0.0.1:8000/payments/2
curl -s http://127.0.0.1:8000/payments/999   # {"detail":"Payment 999 not found"}
```

**Вебхук банка: успешная оплата** → `200`

```bash
curl -s -X POST http://127.0.0.1:8000/webhooks/bank \
  -H "Content-Type: application/json" \
  -d '{"payment_id":2,"status":"succeeded"}'
```

```json
{"result":"ok"}
```

**Вебхук банка: повтор того же статуса** → `409`, статус не меняется

```bash
curl -s -X POST http://127.0.0.1:8000/webhooks/bank \
  -H "Content-Type: application/json" \
  -d '{"payment_id":2,"status":"succeeded"}'
```

```json
{"error":"invalid_transition"}
```

Допустимые переходы: `pending → succeeded`, `pending → failed`, `succeeded → refunded`.

## Принятые решения

- **Несуществующий `tariff_id` → 422**, а не 404. ТЗ молчит; ссылка в теле запроса считается невалидной.
  Ответ: `{"detail": "Tariff 99 not found"}`.
- **Неизвестный промокод → 422** (`{"detail": "Unknown promo code: NOPE"}`), платёж не создаётся.
- **Пустой промокод** (`""` или строка из пробелов) = промокода нет, скидка 0 %, ответ `201`. Причина:
  фронтенд часто шлёт `""` из незаполненного поля. Регистр и пробелы по краям не важны.
- **Повтор с тем же `Idempotency-Key` и другим телом** → `200` с исходным платежом. Тело повторного
  запроса не сравнивается с исходным; проверяется только его схема (невалидный JSON или email → `422`).
  Тариф и промокод повтор не проверяет: с несуществующим тарифом он всё равно вернёт `200`. В продакшене
  стоило бы сверять хеш тела и отвечать `409` или `422` при расхождении; здесь это не сделано ради простоты.
- **Длина `Idempotency-Key`** от 1 до 255 символов (как колонка в БД), иначе `422`.
- **Округление скидки вниз** до копейки: `price * percent // 100`, дробная копейка остаётся у школы.
- **Рассрочка:** `divmod(amount, months)`, лишние копейки достаются первым платежам, сумма графика всегда
  равна сумме к оплате. Пример: `1990000 / 3` → `[663334, 663333, 663333]`.
- **Повтор того же статуса вебхуком → `409`** (по букве ТЗ: допустимы только перечисленные переходы).
- **Запрещённый переход не меняет статус:** смена выполняется `UPDATE ... WHERE status = :old`, гонка двух
  вебхуков тоже даёт `409`.
- **Вебхук не проверяет подпись.** Поле `WEBHOOK_SECRET` есть в настройках, но проверка подписи
  (`X-Signature`) не реализована: это бонусная фича, в основной части ТЗ её нет.
- **SQLite по умолчанию**, чтобы проект запускался без внешних сервисов. Другая БД задаётся через
  `DATABASE_URL`, но драйвер Postgres в `requirements*.txt` не входит (его нужно установить самостоятельно),
  и приложение на Postgres не проверялось.
- **Ошибки валидации** — стандартный формат FastAPI (`422`, `detail` — список).

## Структура проекта

```
app/main.py         # create_app(), lifespan (таблицы, сидинг тарифов), обработчики ошибок
app/config.py       # настройки; app/db.py — engine и сессия на запрос
app/models.py       # Tariff, Payment, enum-ы; schemas.py — Pydantic-схемы; errors.py — исключения
app/services/       # pricing.py — чистые функции денег; payments.py, tariffs.py — бизнес-правила
app/routers/        # HTTP: tariffs.py, payments.py, webhooks.py
tests/              # unit-тесты (pricing) и API-тесты (TestClient) с проверкой состояния БД
```
