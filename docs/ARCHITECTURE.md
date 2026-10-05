# Архитектура Foundation

## Слой данных v0.2

`brokers/base.py` задаёт read capability; `brokers/tinvest.py` реализует фиксированный Sandbox endpoint и allowlist только методов чтения. Метода отправки заявки нет. `provision_token.py` принимает токен только через скрытый терминальный ввод, валидирует его до замены и сохраняет encrypted token file. В бизнес-БД хранится случайный reference, который не возвращается через API. Ключи и ciphertext разделены по Docker volumes, ротация защищена flock и atomic replace.

`market_data.py` собирает подтверждённые ответы, затем блокирует connection row и проверяет generation до атомарного сохранения истории и снимка. Любая замена токена, отключение или смена счёта меняет generation. Старый запрос не может опубликовать устаревшее состояние подключения. Redis очередь объединяет запросы, worker берёт distributed lock; время жизни lock 600 секунд. Этот механизм предназначен только для reads, не для торгового исполнения.

Worker heartbeat выполняется независимо от загрузки данных, которая работает в отдельном потоке. Сбор REST-снимков раз в 5 минут не изображает realtime. Quote freshness проверяется по времени источника. Снимки имеют user_id и SANDBOX account_id; они не изменяют локальный виртуальный cash. Идентификаторы quote/candle/snapshot возвращаются для будущего evidence.

Миграция 0002 добавляет broker_connections, instruments, candles, quotes, market_snapshots. Восстановление connection status не снимает SAFE MODE и не включает Autopilot.

Дальнейшие разделы описывают Foundation; пункты о будущем хранилище и адаптере заменены реализацией v0.2 выше. Streaming, execution, analysis, broker reconciliation и production hardening по-прежнему отсутствуют.

## Границы доверия

Frontend обращается только к same-origin `/api` через серверный proxy Next.js. Backend хранит сессии и бизнес-данные в PostgreSQL. Redis обеспечивает ограничения запросов и heartbeat worker. База и Redis доступны только внутри Docker-сети.

Risk Engine — чистая функция без брокерского доступа. Он проверяет proposal и рассчитывает допустимые лоты; его результат нельзя считать разрешением отправить реальную заявку в этой версии. Будущий Order Manager обязан заново проверить актуальное состояние в транзакции, зарезервировать средства и единолично обращаться к Broker Adapter. Пропуски комиссии и slippage, превышающие рассчитанный риск, должны блокировать вход.

LLM в торговое ядро не включён. AI Analyst появится как потребитель сохранённых evidence records без broker credentials и права менять production-стратегии.

## Сохранённые данные

Миграция 0001 создаёт users, sessions, portfolios, audit_log, decisions, orders, subscriptions; 0002 добавляет брокерские подключения и рыночную историю. Бизнес-записи принадлежат user_id; портфели и ключи идемпотентности разделены по mode. Остальная схема из ТЗ появится с соответствующими модулями.

API фильтрует все доступные записи по текущему пользователю. Пароли хешируются Argon2; в БД сохраняется только SHA-256 от случайного session token. Журнал не имеет пользовательских операций редактирования/удаления. Защита append-only на уровне DB-ролей и WORM export — будущая задача; текущая локальная DB-роль обладает административными правами.

## Состояния

Sandbox стартует в SAFE MODE, Autopilot STOPPED. REAL запрещён сервером без конфигурационного обхода. Start создаёт аудит и SKIP, затем возвращает 409. Никаких заявок не отправляется. Worker проверяет инфраструктуру каждые 10 секунд и собирает подключённые Sandbox-источники по очереди. Frontend получает подтверждённое состояние каждые 30 секунд; stream/SSE предстоит реализовать.

UNKNOWN нельзя перевести в SENDING обычным переходом; требуется отдельный результат сверки с брокером. Уникальный ключ orders `(user_id, mode, idempotency_key)` подготовлен, но распределённые locks, резервирование капитала, исполнение и атомарный Order Manager ещё не реализованы и не заявляются готовыми.

## Дальнейшее развитие брокерского слоя

Добавить внешнюю KMS, разрешения production-ролей, streaming и gap recovery. Не добавлять токены в frontend, логи, Git или бизнес-таблицы в открытом виде. Входные market snapshots содержат UTC-время источника, trading status, UID/FIGI и ссылки на исходные записи. Отсутствующие и устаревшие данные запрещают BUY.

Тесты ядра используют явные fixtures. Они не отображаются как цены, сделки или показатели продукта.

## Production gaps

HTTPS ingress, секретное хранилище, email verification/reset, OWNER provisioning, per-user rate limits за proxy, cleanup/revocation всех сессий, CSP nonce, метрики и алерты, резервное копирование и restore test, изоляция DB-ролей, tenant-scoped внешние ключи orders/decisions и PostgreSQL concurrency tests обязательны до production. Никаких реальных средств до paper test и отдельной активации.

Стек и сборка сверены с официальными документами [FastAPI Docker](https://fastapi.tiangolo.com/deployment/docker/) и [Next.js installation](https://nextjs.org/docs/app/getting-started/installation).
