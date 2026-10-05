# Архитектура Foundation

## Границы доверия

Frontend обращается только к same-origin `/api` через серверный proxy Next.js. Backend хранит сессии и бизнес-данные в PostgreSQL. Redis обеспечивает ограничения запросов и heartbeat worker. База и Redis доступны только внутри Docker-сети.

Risk Engine — чистая функция без брокерского доступа. Он проверяет proposal и рассчитывает допустимые лоты; его результат нельзя считать разрешением отправить реальную заявку в этой версии. Будущий Order Manager обязан заново проверить актуальное состояние в транзакции, зарезервировать средства и единолично обращаться к Broker Adapter. Пропуски комиссии и slippage, превышающие рассчитанный риск, должны блокировать вход.

LLM в торговое ядро не включён. AI Analyst появится как потребитель сохранённых evidence records без broker credentials и права менять production-стратегии.

## Сохранённые данные

Миграция 0001 создаёт users, sessions, portfolios, audit_log, decisions, orders, subscriptions. Бизнес-записи принадлежат user_id; портфели и ключи идемпотентности разделены по mode. Полная схема из ТЗ появится с соответствующими модулями, вместо пустых таблиц, создающих видимость готовности.

API фильтрует все доступные записи по текущему пользователю. Пароли хешируются Argon2; в БД сохраняется только SHA-256 от случайного session token. Журнал не имеет пользовательских операций редактирования/удаления. Защита append-only на уровне DB-ролей и WORM export — будущая задача; текущая локальная DB-роль обладает административными правами.

## Состояния

Sandbox стартует в SAFE MODE, Autopilot STOPPED. REAL запрещён сервером без конфигурационного обхода. Start создаёт аудит и SKIP, затем возвращает 409. Никаких заявок не отправляется. Worker проверяет инфраструктуру каждые 10 секунд; он ещё не сканирует рынок. Frontend получает подтверждённое состояние каждые 30 секунд; stream/SSE предстоит реализовать.

UNKNOWN нельзя перевести в SENDING обычным переходом; требуется отдельный результат сверки с брокером. Уникальный ключ orders `(user_id, mode, idempotency_key)` подготовлен, но распределённые locks, резервирование капитала, исполнение и атомарный Order Manager ещё не реализованы и не заявляются готовыми.

## Перед подключением брокера

Создать отдельное encrypted secret storage с rotation/revocation и account selection. Не добавлять токены в frontend, логи, Git или бизнес-таблицы в открытом виде. Входные market snapshots должны содержать UTC-время источника, trading status, UID/FIGI и ссылки на исходные записи. Отсутствующие и устаревшие данные запрещают BUY.

Тесты ядра используют явные fixtures. Они не отображаются как цены, сделки или показатели продукта.

## Production gaps

HTTPS ingress, секретное хранилище, email verification/reset, OWNER provisioning, per-user rate limits за proxy, cleanup/revocation всех сессий, CSP nonce, метрики и алерты, резервное копирование и restore test, изоляция DB-ролей, tenant-scoped внешние ключи orders/decisions и PostgreSQL concurrency tests обязательны до production. Никаких реальных средств до paper test и отдельной активации.

Стек и сборка сверены с официальными документами [FastAPI Docker](https://fastapi.tiangolo.com/deployment/docker/) и [Next.js installation](https://nextjs.org/docs/app/getting-started/installation).
