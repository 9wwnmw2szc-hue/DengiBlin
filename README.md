# MarketBrain

Автономная система анализа рынка и управления торговым портфелем. Репозиторий: **DengiBlin**, продукт: **MarketBrain**.

**Текущая версия — Foundation v0.1, не готовый торговый MVP.** Реальных заявок, подключения брокера и автономной торговли в этой версии нет. Недоступные функции обозначены явно; котировки, сделки и доходность не подменяются демоданными.

## Что работает

- FastAPI backend и Next.js / TypeScript frontend, адаптивный тёмный интерфейс.
- Регистрация, вход и выход; Argon2, серверные сессии, HttpOnly cookies, проверка Origin, Redis rate limit.
- Отдельный Sandbox каждого пользователя с начальным виртуальным капиталом **1 000 ₽** и изменяемым балансом.
- Постоянные журналы аудита и решений; попытка запуска без данных сохраняет SKIP с причиной.
- Независимый Risk Engine: денежные расчёты Decimal, лоты, комиссии, ограничения капитала, ликвидности, волатильности и корреляции.
- Запрет BUY при SAFE MODE, устаревших данных, неизвестной заявке, закрытом рынке и рассинхронизации.
- Правила переходов заявок и запрет повторной отправки UNKNOWN до reconciliation. Это пока доменные правила, а не работающий Order Manager.
- PostgreSQL, Redis, миграции Alembic, отдельный worker инфраструктуры, health checks, Docker Compose, CI.

## Локальный запуск

Требуются Docker Engine / Docker Desktop и Docker Compose v2. Рекомендуется не менее 4 GB свободной памяти.

```sh
cp .env.example .env
# В .env замените POSTGRES_PASSWORD длинным случайным паролем из букв и цифр.
docker compose up --build -d --wait --wait-timeout 300
```

Откройте **http://localhost:3000**, создайте аккаунт с паролем от 12 символов. Миграции выполняются автоматически до старта backend. Порт доступен только на localhost; PostgreSQL и Redis наружу не публикуются. Перезапуск сохраняет пользователей и баланс в Docker volumes.

```sh
docker compose logs -f backend worker
docker compose down
```

`down` сохраняет данные. Не добавляйте `-v`, если хотите сохранить историю.

На сервере нужен отдельный HTTPS reverse proxy, `APP_ORIGIN=https://ваш-домен` и `COOKIE_SECURE=true`. Этот Compose предназначен для локальной разработки. Секреты не коммитить; broker token никогда не вводить в чат. Production hardening и секретное хранилище ещё не реализованы.

## Проверки

```sh
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
DATABASE_URL=sqlite:////tmp/marketbrain-migration.db .venv/bin/alembic upgrade head
DATABASE_URL=sqlite:////tmp/marketbrain-migration.db .venv/bin/alembic check
```

```sh
cd frontend
corepack enable
pnpm install --frozen-lockfile
pnpm build
pnpm typecheck
```

CI проверяет backend, frontend, миграции и запуск всей инфраструктуры. Статус конкретного запуска CI смотрите в GitHub Actions; наличие workflow не означает, что он уже успешно прошёл.

## Следующие этапы

Первичный источник требований: [MASTER-ТЗ v1.0](docs/MASTER_SPEC.md). Честный статус реализации: [ROADMAP](docs/ROADMAP.md). Границы модулей и ограничения: [ARCHITECTURE](docs/ARCHITECTURE.md).

Следующий этап — T-Invest **Sandbox / read-only data adapter**, нормализация и сохранение инструментов, свечей, статусов торгов и портфеля. Затем аналитика, стратегии, Decision/Risk/Exit, Order Manager, reconciliation, Sandbox Autopilot, Telegram и длительный paper test. REAL требует отдельного решения владельца после тестирования.

Все новые аккаунты имеют роль USER. OWNER не назначается по непроверенному email. Проверка email, восстановление пароля, подписки и полномасштабная наблюдаемость остаются в плане.

**Если нет корректных данных — NO TRADE.**
