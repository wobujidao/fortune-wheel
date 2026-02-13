from __future__ import annotations

import asyncio
import logging

import uvicorn
from aiogram import Bot, Dispatcher
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bot.api.routes import admin_router, public_router
from bot.config import API_HOST, API_PORT, BOT_TOKEN, WEBAPP_URL
from bot.db.database import init_db
from bot.handlers import admin as admin_handlers
from bot.handlers import start as start_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---- FastAPI ----
app = FastAPI(title="Колесо Фортуны API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[WEBAPP_URL],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-Telegram-Init-Data"],
)
app.include_router(public_router)
app.include_router(admin_router)

# ---- Aiogram ----
bot = Bot(token=BOT_TOKEN)
app.state.bot = bot
dp = Dispatcher()
dp.include_router(start_handlers.router)
dp.include_router(admin_handlers.router)


@app.on_event("startup")
async def on_startup() -> None:
    logger.info("Инициализация БД...")
    await init_db()
    logger.info("Запуск polling бота...")
    asyncio.create_task(dp.start_polling(bot))


@app.on_event("shutdown")
async def on_shutdown() -> None:
    logger.info("Остановка бота...")
    await bot.session.close()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def main() -> None:
    uvicorn.run(
        app,
        host=API_HOST,
        port=API_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
