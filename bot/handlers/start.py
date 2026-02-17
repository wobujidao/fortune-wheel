from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from bot.config import WEBAPP_URL

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Приветствие + кнопка открытия Mini App."""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎰 Испытай удачу!",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            ]
        ]
    )
    await message.answer(
        "🎉 <b>Колесо Фортуны</b>\n"
        "<b>ГКУ МО ЦБ МО</b>\n\n"
        "Крутите колесо и забирайте гарантированный подарок "
        "в честь 23 Февраля!\n\n"
        "Нажмите кнопку ниже, чтобы открыть колесо 👇",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
