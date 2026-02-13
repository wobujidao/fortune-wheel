from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import func, select

from bot.config import WEBAPP_URL
from bot.db.database import async_session
from bot.db.models import Admin, Spin

router = Router()


async def _is_admin(tg_user_id: int) -> bool:
    """Проверяет, является ли пользователь админом."""
    async with async_session() as session:
        result = await session.execute(
            select(Admin).where(Admin.tg_user_id == tg_user_id, Admin.role == "admin")
        )
        return result.scalar_one_or_none() is not None


async def _is_viewer(tg_user_id: int) -> bool:
    """Проверяет, является ли пользователь админом или просмотрщиком."""
    async with async_session() as session:
        result = await session.execute(
            select(Admin).where(Admin.tg_user_id == tg_user_id)
        )
        return result.scalar_one_or_none() is not None


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    """Ссылка на веб-админку (только для админов)."""
    if not message.from_user:
        return
    if not await _is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к админке.")
        return

    admin_url = f"{WEBAPP_URL}/admin"
    await message.answer(
        "🔧 <b>Панель администратора</b>\n\n"
        f"Откройте админку: {admin_url}",
        parse_mode="HTML",
    )


@router.message(Command("results"))
async def cmd_results(message: Message) -> None:
    """Краткая сводка результатов (для админов и просмотрщиков)."""
    if not message.from_user:
        return
    if not await _is_viewer(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к результатам.")
        return

    async with async_session() as session:
        total_result = await session.execute(select(func.count(Spin.id)))
        total = total_result.scalar() or 0

    await message.answer(
        "📊 <b>Сводка результатов</b>\n\n"
        f"Всего вращений: <b>{total}</b>",
        parse_mode="HTML",
    )
