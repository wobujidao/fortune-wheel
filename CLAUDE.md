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

- `bot` (fortune-bot) — Python: aiogram + FastAPI, expose 8000 (внутренний), non-root user `appuser`
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

- `frontend/index.html` — Mini App с колесом. Призы загружаются из `GET /api/prizes` с fallback на захардкоженные. Canvas: два слоя (колесо + лампочки). Telegram WebApp SDK для авторизации.
- `frontend/admin.html` — админка с тремя вкладками: Результаты (поиск, удаление, CSV-экспорт через clipboard), Призы (CRUD), Доступ (управление ролями). Авторизация через `X-Telegram-Init-Data` заголовок.

### API (`bot/api/routes.py`)

- Public: `GET /api/prizes`, `POST /api/spin`, `GET /api/check/{tg_user_id}`
- Admin: CRUD призов, результаты, CSV-экспорт, сброс, управление пользователями
- Auth: `bot/api/auth.py` — HMAC-SHA256 валидация Telegram initData
- Логирование: все админские операции логируются через `logger.info()`

### Database (`bot/db/`)

SQLite, три таблицы: `prizes`, `spins`, `admins`. При первом запуске `init_db()` создаёт таблицы и сидит 6 дефолтных призов + админов из `ADMIN_IDS`. Индекс на `spins.created_at`.

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

## Key Conventions

- "Колесо **Ф**ортуны" — заглавная Ф
- Равная вероятность всех секторов
- Поддержка 2–12 секторов
- Полная типизация Python-кода
- `.env` — никогда не коммитится; шаблон в `.env.example`
- `data/` — исключена из git
