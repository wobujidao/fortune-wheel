# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Важные правила

- **Всегда отвечай на русском языке.**
- **Вместо редактора nano используй mcedit.**

## Project Overview

Telegram Mini App "Колесо Фортуны" для сотрудников ЦБ МО. Пользователи крутят колесо через Telegram-бот и выигрывают гарантированный бонус к рабочему графику. Одна попытка на пользователя до сброса через админку. Проект рассчитан на ежегодное переиспользование.

- Bot: [@fortune_cbmo_bot](https://t.me/fortune_cbmo_bot)
- Domain: fortune.demidov.info
- Язык UI и комментариев: русский

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vanilla HTML5 + CSS3 + JS (Canvas API), Telegram WebApp SDK |
| Backend | Python 3.13, FastAPI 0.115, Pydantic v2 (<2.10) |
| Bot | aiogram 3.15 |
| Database | SQLite + aiosqlite + SQLAlchemy 2.0 async |
| Auth | Telegram WebApp initData (HMAC-SHA256) |
| Deploy | Docker Compose (2 контейнера: bot + nginx) |

## Build & Run

```bash
cp .env.example .env   # заполнить BOT_TOKEN, ADMIN_IDS
docker compose up -d --build
```

Фронтенд не требует сборки — монтируется как Docker volume (изменения в `frontend/` применяются без пересборки). Бэкенд требует `--build` при изменениях.

## Architecture

### Единый процесс (`bot/main.py`)

FastAPI + aiogram polling работают в одном процессе:
- FastAPI обслуживает API на порту 8000
- aiogram polling запускается через `asyncio.create_task(dp.start_polling(bot))` в `on_startup`

**Важно**: `uvicorn.run(app, ...)` — передавать объект `app`, НЕ строку `"bot.main:app"`. Строковый импорт вызывает повторную регистрацию роутеров aiogram.

### Docker-архитектура

- `bot` (fortune-bot) — Python: aiogram + FastAPI, expose 8000 (внутренний), non-root user `appuser`, entrypoint с `gosu` для фикса прав на volume
- `nginx` (fortune-nginx) — reverse proxy, порт 8000:80, раздаёт `frontend/` как статику
- Внешний Nginx Proxy Manager (192.168.5.4) проксирует на 192.168.5.11:8000
- Healthcheck: бот проверяется каждые 30s через `/health`, nginx зависит от `service_healthy`

### Безопасность

- **CORS**: только `WEBAPP_URL`, без wildcard
- **CSP**: `default-src 'self'`, script/style `'unsafe-inline'` (нужен для inline-кода), `frame-ancestors` для Telegram WebView
- **Security headers**: X-Content-Type-Options, X-Frame-Options, Referrer-Policy
- **Rate limiting**: `/api/spin` — 5 req/s per IP, burst=3
- **XSS-защита**: фронтенд использует `textContent` и DOM API вместо `innerHTML`
- **Race condition**: `/api/spin` и создание админа используют `IntegrityError` вместо SELECT-before-INSERT
- **Валидация**: Pydantic Field validators (min_length, max_length, pattern, gt, ge, le)

### Frontend

- `frontend/index.html` — Mini App с колесом. Призы загружаются из `GET /api/prizes` с fallback на захардкоженные. Canvas: два слоя (колесо 300×300 + лампочки 360×360), внутренняя разметка процентная для масштабирования. Размер колеса адаптируется под высоту экрана через `min(320px, 80vw, 42dvh)`. Telegram WebApp SDK для авторизации и HapticFeedback. Звуковые эффекты через Web Audio API (тиканье секторов + фанфары). Loading-спиннер, toast-уведомления об ошибках, BackButton для модалки. Два стиля указателя: top (стрелка сверху) и center (стрелка из хаба вверх) — переключается в админке. Поддерживает режим разработки (dev mode) через `localStorage`.
- `frontend/admin.html` — админка с пятью вкладками: Результаты (поиск, удаление, CSV-экспорт, статистика), Призы (CRUD + drag & drop сортировка), Доступ (управление ролями), Настройки (стиль указателя + режим разработки), Лог (аудит-лог). Mobile-first: на экранах <600px таблицы заменяются карточками (CSS `data-label` + `::before`), ненужные колонки скрываются (`.hide-mobile`). Toast-уведомления (fixed bottom), кастомный confirm-диалог вместо browser `confirm()`, loading-спиннеры при загрузке данных, пустые состояния для таблиц. BackButton для закрытия. Авторизация через `X-Telegram-Init-Data` заголовок.

### API (`bot/api/routes.py`)

- Public: `GET /api/prizes`, `POST /api/spin`, `GET /api/check/{tg_user_id}`, `GET /api/settings`
- Admin: CRUD призов, результаты, CSV-экспорт, сброс, управление пользователями, аудит-лог, настройки (`PUT /api/admin/settings`)
- Auth: `bot/api/auth.py` — HMAC-SHA256 валидация Telegram initData с защитой от невалидного JSON/auth_date
- Логирование: все админские операции логируются через `logger.info()` + записываются в таблицу `audit_log` (log_audit() не роняет основной запрос при ошибке)

### Database (`bot/db/`)

SQLite, пять таблиц: `prizes`, `spins`, `admins`, `audit_log`, `settings`. При первом запуске `init_db()` создаёт таблицы и сидит 6 дефолтных призов + админов из `ADMIN_IDS` + настройку `pointer_style=top`. Индексы на `spins.created_at` и `audit_log.created_at`.

### Bot commands (`bot/handlers/`)

- `/start` — кнопка WebApp для открытия Mini App
- `/admin` — кнопка WebApp для открытия админки (только для роли admin)
- `/results` — сводка количества вращений (admin + viewer)

## Known Gotchas

- **pydantic**: aiogram 3.15 требует `pydantic<2.10`
- **greenlet**: обязательна для SQLAlchemy async (`greenlet>=3.0.0` в requirements)
- **Время**: SQLite `func.now()` всегда возвращает UTC. Используем `default=datetime.now` на уровне Python + `TZ=Europe/Moscow` в docker-compose
- **CSV-экспорт**: Telegram WebView блокирует `window.open()`, `a.click()`, `navigator.share()` — используем `navigator.clipboard.writeText()` для копирования в буфер обмена
- **Админка**: открывается только через WebApp-кнопку в Telegram (нужен initData для авторизации)
- **Кэширование**: Telegram WebView агрессивно кэширует — nginx отдаёт `Cache-Control: no-cache, no-store` на все ответы
- **Memory leaks**: Canvas-анимации (колесо, звёзды) используют отслеживание RAF ID + cancelAnimationFrame при resize
- **SQLite readonly**: Docker volume `data/` создаётся от root — `entrypoint.sh` делает `chown appuser` перед запуском через `gosu`
- **Canvas лампочек**: размер canvas 360×360 (не 330!) — при меньшем размере красный обод с lineWidth 26 обрезается со всех сторон. Колесо 300×300 внутри — позиционирование через проценты (8.33% offset, 83.33% size), стрелки-указатели тоже процентные (width 8.9% / 12.2%) для корректного масштабирования при разных размерах wheel-outer
- **Mobile-first layout**: весь контент (заголовок + колесо + легенда + кнопка) должен помещаться без скролла в Telegram WebApp. Колесо адаптируется через `min(320px, 80vw, 42dvh)` с fallback на `vh`. Легенда компактная: gap 2px, padding 4px 10px, номера 20×20
- **random vs secrets**: `random.choice()` (Mersenne Twister) в LXC-контейнере может давать одинаковые результаты при одновременных запросах — использовать `secrets.choice()` (OS CSPRNG)
- **Режим разработки**: флаг `devMode` передаётся через `localStorage` между админкой и колесом (один origin). В dev mode колесо выбирает приз локально без API, не сохраняет результат, позволяет крутить бесконечно
- **Web Audio API**: AudioContext создаётся лениво (первый вызов playTick/playWin) — обход блокировки autoplay в iOS/Android. Состояние звука в `localStorage('soundEnabled')`
- **HapticFeedback**: обязательна проверка `tg && tg.HapticFeedback` перед вызовом — на десктопе объект отсутствует
- **Drag & Drop в таблице**: HTML5 DnD на `<tr>` — при drop нужно пересортировать DOM и отправить PUT `/api/admin/prizes/reorder`, при ошибке откатить через `loadPrizes()`. После успешного сохранения — `loadPrizes()` для обновления номеров
- **Порядок маршрутов FastAPI**: `PUT /prizes/reorder` ОБЯЗАТЕЛЬНО должен стоять ПЕРЕД `PUT /prizes/{prize_id}` — иначе "reorder" интерпретируется как `{prize_id}` → 422
- **Позиции призов 1-based**: position начинается с 1, не с 0. Дефолт в модели, Pydantic (ge=1), форме и drag & drop — всё 1-based
- **auth.py парсинг**: `int(auth_date)` и `json.loads(user)` могут кинуть исключение — обёрнуты в try-except, чтобы возвращать 401, а не 500
- **log_audit() отказоустойчивость**: обёрнут в try-except + `logger.exception()` — ошибка записи аудита не должна ломать основной запрос
- **Drag & Drop утечка обработчиков**: `enablePrizeDragDrop()` вызывается при каждом `loadPrizes()` — обязательно `removeEventListener` перед `addEventListener`
- **Fetch без try-catch**: все admin fetch-вызовы должны иметь try-catch с показом `showMsg('Сетевая ошибка')`, иначе при обрыве сети — необработанный Promise rejection
- **Админка: таблицы на мобильном**: на экранах <600px CSS превращает `<tr>` в карточки через `display: block` + `data-label` атрибуты на `<td>` + `::before` pseudo-элементы. `.hide-mobile` скрывает только внутренний ID БД и «Добавил» — Telegram ID всегда виден. В аудит-логе имя админа добавляется в детали (т.к. столбец «Админ» скрыт)
- **Админка: confirm()**: заменён на кастомный `customConfirm(title, text)` → Promise<boolean>. Styled modal в тёмной теме
- **Админка: Toast**: `showMsg()` теперь создаёт fixed-position toast внизу экрана (вместо `#msg` div вверху). Авто-удаление через 3.5с
- **Админка: Dev mode**: перенесён из основного layout в вкладку «Настройки»
- **Админка: ролевая модель фронтенда**: при инициализации проверяется admin-only эндпоинт (`/api/admin/audit`). Если 200 → `body.role-admin`, CSS-класс `.admin-only` показывает элементы. Viewer видит только вкладки «Результаты» и «Призы» (без кнопок действий). Drag & drop отключён для viewer
- **SQLite WAL mode**: обязательно `PRAGMA journal_mode=WAL` при init_db() — позволяет читать во время записи. Без WAL при 300 одновременных запросах будут ошибки «database is locked»
- **SQLite busy_timeout**: `connect_args={"timeout": 5}` в create_async_engine — при блокировке ждёт 5 сек вместо мгновенной ошибки
- **Rate limiting по реальному IP**: nginx видит IP Nginx Proxy Manager (192.168.5.4), а не пользователя. Используем `map $http_x_real_ip` для получения реального IP из заголовка, иначе все 300 пользователей делят лимит 5 req/s
- **Удаление админов**: нельзя удалить самого себя (`admin.tg_user_id == user["id"]`) и последнего администратора (`count(role=="admin") <= 1`). Без этих проверок система может стать неуправляемой
- **Лимиты активных призов в update_prize**: `create_prize` проверяет max 12, но `update_prize` тоже должен — при активации проверяем `active_count >= 12`, при деактивации `active_count <= 2`. Без этого можно обойти лимиты через редактирование
- **except Exception, не BaseException**: в `get_admin_users` и `create_admin_user` при вызове `bot.get_chat()` — ловить только `Exception`, не `BaseException`. Иначе перехватываются `CancelledError`/`SystemExit`, мешая graceful shutdown
- **Команда /admin для viewer**: `cmd_admin` использует `_is_viewer()` (не `_is_admin()`), чтобы viewer тоже получал WebApp-кнопку для открытия админки. Ролевая модель фронтенда сама ограничивает доступные вкладки
- **loadResults() обработка ошибок**: catch-блок показывает toast (`showMsg`) вместо скрытия `#app` — иначе сетевая ошибка при переключении вкладки убивает весь интерфейс. Проверка доступа (noAccess) выполняется только в `initAdmin()`
- **CSS .admin-only и flex**: `body.role-admin .admin-only { display: revert }` перебивает `display: flex` у `.actions` из-за более высокой специфичности. Нужно отдельное правило `body.role-admin .actions.admin-only { display: flex }` (аналогично `.tab.admin-only { display: inline-flex }`)

## Key Conventions

- "Колесо **Ф**ортуны" — заглавная Ф
- Равная вероятность всех секторов (`secrets.choice` — криптографический CSPRNG)
- Поддержка 2–12 секторов
- Полная типизация Python-кода
- `.env` — никогда не коммитится; шаблон в `.env.example`
- `data/` — исключена из git
