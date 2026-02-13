from __future__ import annotations

import logging

from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import ADMIN_IDS, DB_PATH
from bot.db.models import Admin, AuditLog, Base, Prize  # noqa: F401

logger = logging.getLogger(__name__)

engine = create_async_engine(
    f"sqlite+aiosqlite:///{DB_PATH}",
    echo=False,
    connect_args={"timeout": 5},
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

DEFAULT_PRIZES = [
    {"text": "3-часовой перерыв на обед", "icon": "🍽️", "color": "#4A90D9", "position": 1},
    {"text": "День отдыха в Ваш ДР", "icon": "🎂", "color": "#E8734A", "position": 2},
    {"text": "Завершение работы на 2 часа раньше", "icon": "⏰", "color": "#F5C242", "position": 3},
    {"text": "Дополнительный выходной", "icon": "🌴", "color": "#D95B5B", "position": 4},
    {"text": "Начало работы на 2 часа позже", "icon": "😴", "color": "#5BBD8C", "position": 5},
    {"text": "Завершение работы в обед (в 14:00)", "icon": "🏠", "color": "#9B6EC5", "position": 6},
]


async def init_db() -> None:
    """Создаёт таблицы и сидирует начальные данные (призы + админы из .env)."""
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA busy_timeout=5000"))
        await conn.run_sync(Base.metadata.create_all)

        # Миграция: добавляем колонки к admins, если их нет
        def _migrate_admins(sync_conn: object) -> None:
            cols = [c["name"] for c in inspect(sync_conn).get_columns("admins")]
            if "tg_username" not in cols:
                sync_conn.execute(text("ALTER TABLE admins ADD COLUMN tg_username TEXT"))  # type: ignore[union-attr]
            if "tg_first_name" not in cols:
                sync_conn.execute(text("ALTER TABLE admins ADD COLUMN tg_first_name TEXT"))  # type: ignore[union-attr]

        await conn.run_sync(_migrate_admins)

    async with async_session() as session:
        # Сидируем призы, если таблица пуста
        result = await session.execute(select(Prize).limit(1))
        if result.scalar_one_or_none() is None:
            for p in DEFAULT_PRIZES:
                session.add(Prize(**p))
            logger.info("Сидированы %d призов по умолчанию", len(DEFAULT_PRIZES))

        # Сидируем начальных админов из ADMIN_IDS
        for admin_id in ADMIN_IDS:
            result = await session.execute(
                select(Admin).where(Admin.tg_user_id == admin_id)
            )
            if result.scalar_one_or_none() is None:
                session.add(Admin(tg_user_id=admin_id, role="admin"))
                logger.info("Добавлен начальный админ: %d", admin_id)

        await session.commit()
