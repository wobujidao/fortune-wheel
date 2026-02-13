from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import parse_qs, unquote

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from bot.config import BOT_TOKEN
from bot.db.database import async_session
from bot.db.models import Admin


def validate_init_data(init_data: str, bot_token: str = BOT_TOKEN) -> dict[str, Any]:
    """Валидация Telegram WebApp initData по HMAC-SHA256.

    Возвращает распарсенные данные пользователя.
    Поднимает ValueError при невалидных данных.
    """
    parsed = parse_qs(init_data, keep_blank_values=True)
    # Каждое значение — список, берём первый элемент
    data = {k: v[0] for k, v in parsed.items()}

    received_hash = data.pop("hash", None)
    if not received_hash:
        raise ValueError("hash отсутствует в initData")

    # Проверяем auth_date — не старше 1 часа
    auth_date = data.get("auth_date")
    if auth_date and abs(time.time() - int(auth_date)) > 3600:
        raise ValueError("initData просрочены")

    # data_check_string: отсортированные key=value через \n
    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(data.items())
    )

    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise ValueError("Невалидная подпись initData")

    # Парсим user JSON
    user_raw = data.get("user")
    if user_raw:
        data["user"] = json.loads(unquote(user_raw))

    return data


async def get_current_user(request: Request) -> dict[str, Any]:
    """FastAPI-зависимость: извлекает и валидирует Telegram-пользователя из initData."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if not init_data:
        raise HTTPException(status_code=401, detail="Отсутствует X-Telegram-Init-Data")
    try:
        data = validate_init_data(init_data)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    user = data.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден в initData")
    return user


async def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """FastAPI-зависимость: требует роль admin."""
    tg_user_id = user["id"]
    async with async_session() as session:
        result = await session.execute(
            select(Admin).where(Admin.tg_user_id == tg_user_id, Admin.role == "admin")
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=403, detail="Требуются права администратора")
    return user


async def require_viewer(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """FastAPI-зависимость: требует роль admin или viewer."""
    tg_user_id = user["id"]
    async with async_session() as session:
        result = await session.execute(
            select(Admin).where(Admin.tg_user_id == tg_user_id)
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=403, detail="Доступ запрещён")
    return user
