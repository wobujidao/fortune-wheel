# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Важные правила

- **Всегда отвечай на русском языке.**
- **Вместо редактора nano используй mcedit.**

## Project Overview

Telegram Mini App "Wheel of Fortune" (Колесо Фортуны) for employees of ЦБ МО. Users spin a wheel via a Telegram bot and win a guaranteed workplace perk (e.g., extra day off, late start). One spin per user, prizes valid until next Feb 23. The project is designed for annual reuse with full admin control over prizes and results.

- Bot: [@fortune_cbmo_bot](https://t.me/fortune_cbmo_bot)
- Domain: fortune.demidov.info
- Language: Russian (all UI text, README, comments)

## Current State

Frontend (`frontend/index.html`) — полностью реализован. Backend (Python/FastAPI/aiogram), БД, Docker — реализованы. Admin panel (`frontend/admin.html`) — реализована.

## Tech Stack

| Layer | Technology | Status |
|-------|-----------|--------|
| Frontend | Vanilla HTML5 + CSS3 + JS (Canvas API) | Implemented |
| Backend | Python 3.13+, FastAPI, Pydantic v2 | Implemented |
| Bot | aiogram 3.x | Implemented |
| Database | SQLite + aiosqlite + SQLAlchemy 2.0 async | Implemented |
| Auth | Telegram WebApp initData (HMAC-SHA256) | Implemented |
| Linter | Ruff (Python) | Planned |
| Deploy | Docker + Docker Compose, Nginx reverse proxy | Implemented |

## Build & Run

No build step needed for the frontend — it's a single HTML file. Open `frontend/index.html` in a browser.

When the backend is implemented:
```bash
cp .env.example .env   # configure BOT_TOKEN, ADMIN_IDS
docker compose up -d --build
```

## Architecture

### Frontend (`frontend/index.html`)

Single-file Telegram Mini App with no dependencies or bundler:

- **PRIZES array** (line ~324): Hardcoded 6 prizes with text, color, icon. Will become dynamic via `GET /api/prizes` when backend exists.
- **Canvas rendering**: Two overlapping canvases — one for the wheel (`drawWheel(angle)`), one for animated border lights (`drawLights()` + `animateLights()`).
- **Spin mechanics** (`spin()`): Random prize selection, 6-8 full rotations over 5-6.5s with cubic-bezier easing, pointer bounce on segment crossings.
- **State**: `currentAngle`, `spinning` (lock), `hasPlayed` (one-spin enforcement, client-side only), `userResult`.
- **Visual effects**: Background stars (150 elements, breathing opacity), confetti (60 pieces on win), light bulb animation (400ms cycle).

### Planned Backend (`bot/`)

Described in README.md — Python app combining aiogram bot + FastAPI in one process:

- `bot/main.py` — entry point running both bot and API
- `bot/api/routes.py` — public endpoints (`/api/prizes`, `/api/spin`, `/api/check/{tg_user_id}`) and admin endpoints
- `bot/api/auth.py` — Telegram initData HMAC-SHA256 validation
- `bot/db/models.py` — SQLAlchemy models: `prizes`, `spins`, `admins`
- `bot/handlers/` — Telegram command handlers (`/start`, `/admin`, `/results`)

### Database Schema

Three tables: `prizes` (configurable sectors), `spins` (one per user, stores Telegram identity + prize), `admins` (role-based: admin/viewer). See README.md for full ER diagram.

### API Design

- Public: `GET /api/prizes`, `POST /api/spin`, `GET /api/check/{tg_user_id}`
- Admin: CRUD for prizes, results management, CSV export, user role management, full reset
- All requests validated via Telegram WebApp initData

## Key Conventions

- "Колесо **Ф**ортуны" — capital Ф in Фортуны
- Equal probability across all wheel sectors
- Support 2-12 sectors (admin-configurable)
- Full type annotations required for Python code
- Ruff for Python linting
- Environment config via `.env` (never committed); template in `.env.example`
- Data directory (`data/`) and database files excluded from git
