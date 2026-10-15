# Payments API

Сервис приёма оплаты курсов для онлайн-школы: тарифы, создание платежа с промокодом и рассрочкой,
защита от повторных запросов через `Idempotency-Key` и вебхук банка, который меняет статус платежа.

Реализация тестового задания (далее — ТЗ).

Стек: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.x (синхронно), Alembic, SQLite по умолчанию (Postgres 16
через Docker Compose), pytest + httpx, ruff.

## Бонусы

Сверх основной части ТЗ сделано:

- **Подпись вебхука** — `X-Signature` (HMAC-SHA256 от сырого тела), включается переменной `WEBHOOK_SECRET`;
  пример — в разделе «Примеры запросов».
- **`GET /payments` с фильтрами** `email` и `status`.
- **Docker Compose** — API + Postgres 16 одной командой, раздел «Запуск в Docker».
- **Миграции Alembic** — схема БД создаётся только миграциями (`migrations/`).
- **CI** — GitHub Actions: ruff и pytest на Python 3.11 и 3.14 на каждый push.
- **Правила для ИИ-ассистента** — `CLAUDE.md` (цикл фичи, TDD, границы изменений, коммиты, ревью).

## Требования

- Python 3.11 или новее (проверено на 3.14; CI запускает тесты на 3.11 и 3.14).

## Установка и запуск

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Если `.venv\Scripts\activate` не запускается с сообщением «running scripts is disabled», разрешите
выполнение скриптов для текущего пользователя: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
Либо не активируйте окружение и вызывайте его Python напрямую: `.venv\Scripts\python.exe -m pip install -r requirements-dev.txt`,
`.venv\Scripts\python.exe -m alembic upgrade head` и `.venv\Scripts\python.exe -m uvicorn app.main:app --reload`.

Linux / macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

После запуска Swagger доступен на <http://127.0.0.1:8000/docs>.

`alembic upgrade head` создаёт таблицы (миграции лежат в `migrations/`). Приложение само таблицы не
создаёт: без миграций оно не стартует с ошибкой `no such table: tariffs`. Миграции берут базу из того же
`DATABASE_URL`, что и приложение. Тарифы заполняются при старте приложения. Если `payments.db` осталась
от версии проекта до миграций, удалите её или пометьте как актуальную: `alembic stamp head`.

Новая миграция после правки `app/models.py`: `alembic revision --autogenerate -m "..."`, затем вычитать файл
в `migrations/versions/`. Autogenerate не видит изменений `CHECK`, а для enum-колонок выдаёт каждый `CHECK`
дважды. Поэтому enum-колонки в миграции пишутся вручную: `sa.String(32)` и один именованный `CHECK`, как
в первой миграции. Что схема после миграций совпадает с моделями, проверяет `tests/test_migrations.py`.

Настройки читаются из переменных окружения и из файла `.env` в папке запуска. Шаблон: `.env.example`
(скопировать в `.env`, это необязательно: без `.env` работают значения по умолчанию).

| Переменная       | По умолчанию              | Смысл                                                                       |
| ---------------- | ------------------------- | --------------------------------------------------------------------------- |
| `DATABASE_URL`   | `sqlite:///./payments.db` | Строка подключения к БД; путь к SQLite относительный (файл в папке запуска) |
| `WEBHOOK_SECRET` | пусто                     | Секрет подписи вебхука (`X-Signature`); пусто — подпись не проверяется      |

### Запуск в Docker (API + Postgres)

Нужен Docker с Compose (проверено на Docker Desktop, Compose v5). Версия Python на хосте не важна:

```bash
docker compose up --build
```

Поднимаются Postgres 16, разовый сервис `migrate` (`alembic upgrade head`) и API. Миграции запускаются,
когда база ответила на проверку готовности, API — после того, как миграции успешно завершились.
Swagger — <http://127.0.0.1:8000/docs>, curl-примеры ниже работают без изменений на чистом томе. API
публикуется только на `127.0.0.1:8000` (из локальной сети недоступен); порт должен быть свободен:
остановите локальный `uvicorn`, если он запущен.

Секрет подписи вебхука передаётся через окружение или `.env` в папке проекта (по умолчанию подпись не
проверяется):

```bash
WEBHOOK_SECRET=s3cret docker compose up --build            # bash
```

```powershell
$env:WEBHOOK_SECRET = "s3cret"; docker compose up --build  # PowerShell
```

Остановка — Ctrl+C или `docker compose down`. Данные Postgres лежат в томе и сохраняются между
запусками; начать с чистой базы — `docker compose down -v`. Том, созданный версией проекта до миграций,
`migrate` не примет (`relation "tariffs" already exists`), и API не стартует. Либо удалите том
(`docker compose down -v`), либо пометьте схему как актуальную:
`docker compose run --rm migrate alembic stamp head`, затем снова `docker compose up`. Учётные данные БД
(`payments` / `payments`) в `docker-compose.yml` годятся только для локальной разработки.

## Тесты и линтер

```bash
pytest                       # все тесты (Windows и Linux/macOS одинаково)
pytest tests/test_pricing.py -k schedule -v   # выборочно
ruff check .                 # линт
ruff format --check .        # проверка форматирования
```

Каждый тест работает со своей свежей SQLite во временной папке и не трогает `payments.db`. Схему тестам
создаёт `Base.metadata.create_all`; что миграции дают ту же схему, проверяет `tests/test_migrations.py`.

При прогоне pytest (pytest 9.1.1, httpx 0.28.1) выводится предупреждение `StarletteDeprecationWarning`
про `httpx2`: оно относится к `TestClient`. ТЗ требует `httpx`, поэтому пакет оставлен как есть.

## Примеры запросов (curl)

Ответы ниже получены на запущенном сервере; суммы в копейках.

Примеры рассчитаны на **пустую базу**: id 1 и 2 и ключ `demo-key-1` работают только на свежем
`payments.db`. Если вы уже запускали сервер и делали запросы, остановите его (Ctrl+C), удалите файл
(`rm payments.db` в bash, `Remove-Item payments.db` в PowerShell), выполните `alembic upgrade head` и
запустите сервер снова. Удалять файл при работающем сервере нельзя: на Windows он занят, а на Linux
сервер потеряет таблицы и будет отвечать 500. В Docker база сбрасывается так: `docker compose down -v`,
затем `docker compose up` (миграции выполнятся сами).

Команды записаны в синтаксисе bash: в Git Bash они запускаются как есть. В Windows PowerShell 5.1 `curl` —
алиас `Invoke-WebRequest`, и команды не работают как есть. Там используйте `curl.exe`, а JSON передавайте
из файла, чтобы не экранировать кавычки (проверено на Windows PowerShell 5.1):

```powershell
'{"tariff_id":1,"email":"a@example.com","method":"card","promo_code":" kvitto10 "}' | Set-Content -Encoding ascii body.json
curl.exe -s -w " [%{http_code}]" -X POST http://127.0.0.1:8000/payments -H "Content-Type: application/json" -d "@body.json"
```

Остальные примеры переписываются так же: `curl.exe`, каждая команда в одну строку без `\` в конце строк,
тело запроса из файла. Файл `body.json` создаётся в текущей папке, после прогона его можно удалить.
Запросы без тела (`GET`) работают без изменений: `curl.exe -s http://127.0.0.1:8000/tariffs`.

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

Каждый такой отказ сервер пишет в свой лог (в терминал, где запущен `uvicorn`):
`invalid status transition: payment_id=2 succeeded -> succeeded`.

Допустимые переходы: `pending → succeeded`, `pending → failed`, `succeeded → refunded`.

**Список платежей с фильтрами** → `200`, отсортирован по `id`; `email` и `status` необязательны и
сочетаются по «И»

```bash
curl -s "http://127.0.0.1:8000/payments?status=succeeded"
curl -s "http://127.0.0.1:8000/payments?email=b@example.com&status=succeeded"
curl -s "http://127.0.0.1:8000/payments"   # без фильтров: все платежи
```

```json
[{"id":2,"status":"succeeded","tariff_id":2,"amount":1990000,"discount":0,"method":"installment","installment_months":3,"schedule":[663334,663333,663333],"email":"b@example.com","created_at":"2026-10-15T17:30:32.531035Z"}]
```

Ничего не найдено → `200` и `[]`. Неизвестный `status` (`?status=paid`) и невалидный или пустой `email` → `422`.
`+` в адресе кодируйте как `%2B` (`?email=a%2Btag@example.com`): иначе сервер прочтёт его как пробел.

**Вебхук с подписью** (только если задан `WEBHOOK_SECRET`) → `200`; без подписи или с неверной → `401`

Задайте секрет в `.env` (`WEBHOOK_SECRET=s3cret`) или в переменной окружения и перезапустите сервер.
Подпись — hex (строчными буквами) HMAC-SHA256 от **сырых байтов** тела запроса, ровно в том виде, в каком
тело отправляется. Пример подразумевает, что платёж 2 после предыдущих примеров в статусе `succeeded`:

```bash
BODY='{"payment_id":2,"status":"refunded"}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "s3cret" | awk '{print $NF}')
curl -s -X POST http://127.0.0.1:8000/webhooks/bank \
  -H "Content-Type: application/json" -H "X-Signature: $SIG" -d "$BODY"
```

```json
{"result":"ok"}
```

Неверная или отсутствующая подпись → `401`, платёж не меняется (`{"detail":"Invalid signature"}` или
`{"detail":"Missing signature"}`):

```bash
curl -s -w " [%{http_code}]" -X POST http://127.0.0.1:8000/webhooks/bank \
  -H "Content-Type: application/json" -H "X-Signature: deadbeef" -d "$BODY"
```

В Windows PowerShell 5.1 нет `openssl`: подпись считается средствами .NET, тело берётся из файла
(`--data-binary`, а не `-d`: `-d @файл` удаляет переводы строк, и подпись разошлась бы с телом):

```powershell
$body = '{"payment_id":2,"status":"refunded"}'
[IO.File]::WriteAllText("$PWD\body.json", $body)
$h = New-Object System.Security.Cryptography.HMACSHA256
$h.Key = [Text.Encoding]::UTF8.GetBytes("s3cret")
$sig = -join ($h.ComputeHash([Text.Encoding]::UTF8.GetBytes($body)) | ForEach-Object { $_.ToString("x2") })
curl.exe -s -X POST http://127.0.0.1:8000/webhooks/bank -H "Content-Type: application/json" -H "X-Signature: $sig" --data-binary "@body.json"
```

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
- **`GET /payments`: фильтр `email` — точное совпадение после той же нормализации, что и при создании**
  (`EmailStr`): регистр домена не важен, регистр локальной части важен. Невалидный или пустой `email`
  и неизвестный `status` → `422`, а не пустой список. Пагинации нет: отдаются все подходящие платежи;
  для продакшена нужны `limit`/`offset`. Индекса по `email` нет (это правка схемы).
- **Повтор того же статуса вебхуком → `409`** (по букве ТЗ: допустимы только перечисленные переходы).
- **Запрещённый переход не меняет статус:** смена выполняется `UPDATE ... WHERE status = :old`, гонка двух
  вебхуков тоже даёт `409`.
- **Подпись вебхука проверяется, только если задан `WEBHOOK_SECRET`.** Это бонус вне основной части ТЗ.
  Без секрета вебхук принимает любые запросы. С секретом нужен заголовок `X-Signature`: HMAC-SHA256 от
  сырых байтов тела, hex строчными буквами; нет заголовка или подпись не совпала → `401`
  (`{"detail": "Missing signature"}` / `{"detail": "Invalid signature"}`), платёж не меняется. Подпись
  проверяется раньше валидации тела и поиска платежа, поэтому `404`/`409`/`422` не показывают
  постороннему, существует ли платёж. Исключение: синтаксически битый JSON получает `422` ещё до
  проверки подписи (FastAPI разбирает JSON раньше зависимостей); про платежи такой ответ ничего не
  раскрывает.
- **SQLite по умолчанию**, чтобы проект запускался без внешних сервисов. Другая БД задаётся через
  `DATABASE_URL`; драйвер Postgres (`psycopg`) входит в `requirements.txt`. На Postgres 16 (Docker
  Compose) вручную проверены сценарии из примеров выше, гонка двух вебхуков на один платёж (ровно один
  `200` и один `409`, статус победителя не затёрт) и гонка запросов с одним `Idempotency-Key` (создаётся
  один платёж). Автотесты идут только на SQLite.
- **Схема БД — только через миграции Alembic** (бонус). Приложение при старте таблицы не создаёт, только
  заполняет тарифы; в Docker миграции выполняет отдельный сервис `migrate`, а не каждый экземпляр API.
  Миграции не импортируют код приложения: enum-колонки в них — `VARCHAR` с явным `CHECK`, как их создаёт
  модель. Автотесты миграций идут на SQLite; на Postgres 16 вручную проверено, что схема после миграции
  совпадает с моделями.
- **Отказ вебхуку из-за запрещённого перехода пишется в лог** уровнем `WARNING`: номер платежа, старый и
  новый статус. Тело запроса, заголовки (подпись) и секрет в лог не попадают. Отдельной настройки
  логирования нет: сообщение выводится в stderr стандартным обработчиком Python, простым текстом.
- **Ошибки валидации** — стандартный формат FastAPI (`422`, `detail` — список).

## Структура проекта

```
app/main.py         # create_app(), lifespan (сидинг тарифов), обработчики ошибок
app/config.py       # настройки; app/db.py — engine и сессия на запрос
app/models.py       # Tariff, Payment, enum-ы; schemas.py — Pydantic-схемы; errors.py — исключения
app/services/       # pricing.py — чистые функции денег; payments.py, tariffs.py — бизнес-правила
app/routers/        # HTTP: tariffs.py, payments.py, webhooks.py
app/security.py     # проверка подписи вебхука (HMAC, X-Signature)
alembic.ini         # настройки Alembic; migrations/ — env.py и миграции схемы (versions/)
Dockerfile          # образ API (python:3.11-slim); .dockerignore — белый список для сборки
docker-compose.yml  # API + Postgres 16 + разовые миграции для локального запуска
tests/              # unit-тесты (pricing) и API-тесты (TestClient) с проверкой состояния БД
```
