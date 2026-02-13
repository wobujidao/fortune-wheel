from __future__ import annotations

import csv
import io
import logging
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from bot.api.auth import get_current_user, require_admin, require_viewer, validate_init_data
from bot.db.database import async_session
from bot.db.models import Admin, AuditLog, Prize, Spin

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _admin_display_name(user: dict[str, Any]) -> str:
    """Человекочитаемое имя админа из initData user."""
    name = ((user.get("first_name") or "") + " " + (user.get("last_name") or "")).strip()
    return name or user.get("username") or str(user["id"])


async def log_audit(
    admin_id: int, admin_name: str | None, action: str, details: str | None = None,
) -> None:
    """Записать действие в аудит-лог."""
    try:
        async with async_session() as session:
            session.add(AuditLog(
                admin_id=admin_id, admin_name=admin_name, action=action, details=details,
            ))
            await session.commit()
    except Exception:
        logger.exception("Ошибка записи аудит-лога: action=%s, admin=%d", action, admin_id)


# ---------------------------------------------------------------------------
# Pydantic-схемы
# ---------------------------------------------------------------------------


class PrizeOut(BaseModel):
    id: int
    text: str
    icon: str
    color: str
    position: int
    is_active: bool


class SpinOut(BaseModel):
    prize_id: int
    prize_text: str
    prize_icon: str
    prize_color: str


class CheckOut(BaseModel):
    has_played: bool
    prize: SpinOut | None = None


class SpinResultOut(BaseModel):
    id: int
    tg_user_id: int
    tg_username: str | None
    tg_first_name: str | None
    tg_last_name: str | None
    prize_id: int
    prize_text: str
    created_at: str


class PrizeCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=200)
    icon: str = Field(..., min_length=1, max_length=10)
    color: str = Field(..., pattern=r"^#[0-9A-Fa-f]{6}$")
    position: int = Field(1, ge=1, le=100)


class PrizeUpdate(BaseModel):
    text: str | None = Field(None, min_length=1, max_length=200)
    icon: str | None = Field(None, min_length=1, max_length=10)
    color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    position: int | None = Field(None, ge=1, le=100)
    is_active: bool | None = None


class ReorderItem(BaseModel):
    id: int
    position: int = Field(..., ge=1, le=100)


class AdminCreate(BaseModel):
    tg_user_id: int = Field(..., gt=0)
    role: str = "admin"


class AdminOut(BaseModel):
    id: int
    tg_user_id: int
    tg_username: str | None = None
    tg_first_name: str | None = None
    role: str
    added_by: int | None
    created_at: str


class AuditLogOut(BaseModel):
    id: int
    admin_id: int
    admin_name: str | None
    action: str
    details: str | None
    created_at: str


# ---------------------------------------------------------------------------
# Роутеры
# ---------------------------------------------------------------------------

public_router = APIRouter(prefix="/api", tags=["public"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


# ========================== Публичные эндпоинты ============================


@public_router.get("/prizes", response_model=list[PrizeOut])
async def get_prizes() -> list[PrizeOut]:
    """Список активных призов для колеса."""
    async with async_session() as session:
        result = await session.execute(
            select(Prize)
            .where(Prize.is_active == True)  # noqa: E712
            .order_by(Prize.position)
        )
        prizes = result.scalars().all()
    return [
        PrizeOut(
            id=p.id,
            text=p.text,
            icon=p.icon,
            color=p.color,
            position=p.position,
            is_active=p.is_active,
        )
        for p in prizes
    ]


@public_router.post("/spin", response_model=SpinOut)
async def spin(user: dict[str, Any] = Depends(get_current_user)) -> SpinOut:
    """Крутить колесо — возвращает приз. Одна попытка на пользователя."""
    tg_user_id = user["id"]

    async with async_session() as session:
        # Получаем активные призы
        result = await session.execute(
            select(Prize)
            .where(Prize.is_active == True)  # noqa: E712
            .order_by(Prize.position)
        )
        prizes = result.scalars().all()
        if not prizes:
            raise HTTPException(status_code=503, detail="Нет доступных призов")

        # Случайный приз (равновероятно)
        prize = secrets.choice(prizes)

        # Сохраняем результат — unique constraint на tg_user_id защищает от race condition
        spin_record = Spin(
            tg_user_id=tg_user_id,
            tg_username=user.get("username"),
            tg_first_name=user.get("first_name"),
            tg_last_name=user.get("last_name"),
            prize_id=prize.id,
            prize_text=prize.text,
        )
        session.add(spin_record)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(status_code=409, detail="Вы уже испытали удачу!")

    return SpinOut(
        prize_id=prize.id,
        prize_text=prize.text,
        prize_icon=prize.icon,
        prize_color=prize.color,
    )


@public_router.get("/check/{tg_user_id}", response_model=CheckOut)
async def check_user(tg_user_id: int) -> CheckOut:
    """Проверить, крутил ли пользователь."""
    async with async_session() as session:
        result = await session.execute(
            select(Spin).where(Spin.tg_user_id == tg_user_id)
        )
        spin_record = result.scalar_one_or_none()

        if spin_record is None:
            return CheckOut(has_played=False)

        prize = await session.get(Prize, spin_record.prize_id)

    return CheckOut(
        has_played=True,
        prize=SpinOut(
            prize_id=spin_record.prize_id,
            prize_text=spin_record.prize_text,
            prize_icon=prize.icon if prize else "🎁",
            prize_color=prize.color if prize else "#ffd700",
        ),
    )


# ========================= Админские эндпоинты =============================


@admin_router.get("/results", response_model=list[SpinResultOut])
async def get_results(
    _user: dict[str, Any] = Depends(require_viewer),
) -> list[SpinResultOut]:
    """Все результаты вращений."""
    async with async_session() as session:
        result = await session.execute(select(Spin).order_by(Spin.created_at.desc()))
        spins = result.scalars().all()
    return [
        SpinResultOut(
            id=s.id,
            tg_user_id=s.tg_user_id,
            tg_username=s.tg_username,
            tg_first_name=s.tg_first_name,
            tg_last_name=s.tg_last_name,
            prize_id=s.prize_id,
            prize_text=s.prize_text,
            created_at=s.created_at.isoformat() if s.created_at else "",
        )
        for s in spins
    ]


@admin_router.delete("/results/{spin_id}")
async def delete_result(
    spin_id: int,
    user: dict[str, Any] = Depends(require_admin),
) -> dict[str, str]:
    """Удалить запись вращения."""
    async with async_session() as session:
        result = await session.execute(select(Spin).where(Spin.id == spin_id))
        spin_record = result.scalar_one_or_none()
        if spin_record is None:
            raise HTTPException(status_code=404, detail="Запись не найдена")
        logger.info(
            "Админ %d удалил вращение #%d (user=%d, prize=%s)",
            user["id"], spin_id, spin_record.tg_user_id, spin_record.prize_text,
        )
        details = f"spin #{spin_id}, user={spin_record.tg_user_id}, prize={spin_record.prize_text}"
        await session.delete(spin_record)
        await session.commit()
    await log_audit(user["id"], _admin_display_name(user), "delete_spin", details)
    return {"status": "ok"}


@admin_router.post("/reset")
async def reset_results(
    user: dict[str, Any] = Depends(require_admin),
) -> dict[str, str]:
    """Полный сброс результатов — все пользователи могут крутить заново."""
    async with async_session() as session:
        count_result = await session.execute(select(func.count(Spin.id)))
        count = count_result.scalar() or 0
        await session.execute(delete(Spin))
        await session.commit()
    logger.info("Админ %d сбросил все результаты (%d записей)", user["id"], count)
    await log_audit(user["id"], _admin_display_name(user), "reset_all", f"{count} записей")
    return {"status": "ok", "message": "Все результаты сброшены"}


@admin_router.get("/export")
async def export_results(
    request: Request,
) -> StreamingResponse:
    """Экспорт результатов в CSV.

    Принимает initData через заголовок или query-параметр (для скачивания
    через системный браузер из Telegram WebView).
    """
    init_data = (
        request.headers.get("X-Telegram-Init-Data")
        or request.query_params.get("init_data")
        or ""
    )
    if not init_data:
        raise HTTPException(status_code=401, detail="Отсутствует авторизация")
    try:
        data = validate_init_data(init_data)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    user = data.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    # Проверяем роль viewer
    tg_user_id = user["id"]
    async with async_session() as sess:
        adm = await sess.execute(select(Admin).where(Admin.tg_user_id == tg_user_id))
        if adm.scalar_one_or_none() is None:
            raise HTTPException(status_code=403, detail="Доступ запрещён")

    async with async_session() as session:
        result = await session.execute(select(Spin).order_by(Spin.created_at.desc()))
        spins = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["ID", "Telegram ID", "Username", "Имя", "Фамилия", "Приз ID", "Приз", "Дата"]
    )
    for s in spins:
        writer.writerow([
            s.id,
            s.tg_user_id,
            s.tg_username or "",
            s.tg_first_name or "",
            s.tg_last_name or "",
            s.prize_id,
            s.prize_text or "",
            s.created_at.isoformat() if s.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=results.csv"},
    )


# ---- Аудит-лог ----


@admin_router.get("/audit", response_model=list[AuditLogOut])
async def get_audit_log(
    _user: dict[str, Any] = Depends(require_admin),
) -> list[AuditLogOut]:
    """Лог действий администраторов."""
    async with async_session() as session:
        result = await session.execute(
            select(AuditLog).order_by(AuditLog.created_at.desc()).limit(500)
        )
        logs = result.scalars().all()
    return [
        AuditLogOut(
            id=log.id,
            admin_id=log.admin_id,
            admin_name=log.admin_name,
            action=log.action,
            details=log.details,
            created_at=log.created_at.isoformat() if log.created_at else "",
        )
        for log in logs
    ]


# ---- Управление призами ----


@admin_router.get("/prizes", response_model=list[PrizeOut])
async def admin_get_prizes(
    _user: dict[str, Any] = Depends(require_viewer),
) -> list[PrizeOut]:
    """Все призы (включая неактивные)."""
    async with async_session() as session:
        result = await session.execute(select(Prize).order_by(Prize.position))
        prizes = result.scalars().all()
    return [
        PrizeOut(
            id=p.id,
            text=p.text,
            icon=p.icon,
            color=p.color,
            position=p.position,
            is_active=p.is_active,
        )
        for p in prizes
    ]


@admin_router.post("/prizes", response_model=PrizeOut)
async def create_prize(
    data: PrizeCreate,
    user: dict[str, Any] = Depends(require_admin),
) -> PrizeOut:
    """Добавить приз."""
    async with async_session() as session:
        # Проверяем лимит: не более 12 активных секторов
        count_result = await session.execute(
            select(func.count(Prize.id)).where(Prize.is_active == True)  # noqa: E712
        )
        active_count = count_result.scalar() or 0
        if active_count >= 12:
            raise HTTPException(
                status_code=400, detail="Максимум 12 активных секторов"
            )

        prize = Prize(
            text=data.text,
            icon=data.icon,
            color=data.color,
            position=data.position,
        )
        session.add(prize)
        await session.commit()
        await session.refresh(prize)

    logger.info("Админ %d добавил приз: %s", user["id"], data.text)
    await log_audit(user["id"], _admin_display_name(user), "create_prize", f"{data.icon} {data.text}")
    return PrizeOut(
        id=prize.id,
        text=prize.text,
        icon=prize.icon,
        color=prize.color,
        position=prize.position,
        is_active=prize.is_active,
    )


@admin_router.put("/prizes/reorder")
async def reorder_prizes(
    items: list[ReorderItem],
    user: dict[str, Any] = Depends(require_admin),
) -> dict[str, str]:
    """Изменить порядок секторов."""
    async with async_session() as session:
        for item in items:
            await session.execute(
                update(Prize).where(Prize.id == item.id).values(position=item.position)
            )
        await session.commit()
    logger.info("Админ %d изменил порядок призов (%d шт.)", user["id"], len(items))
    await log_audit(user["id"], _admin_display_name(user), "reorder_prizes", f"{len(items)} призов")
    return {"status": "ok"}


@admin_router.put("/prizes/{prize_id}", response_model=PrizeOut)
async def update_prize(
    prize_id: int,
    data: PrizeUpdate,
    user: dict[str, Any] = Depends(require_admin),
) -> PrizeOut:
    """Редактировать приз."""
    async with async_session() as session:
        prize = await session.get(Prize, prize_id)
        if prize is None:
            raise HTTPException(status_code=404, detail="Приз не найден")
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(prize, field, value)
        await session.commit()
        await session.refresh(prize)

    logger.info("Админ %d обновил приз #%d", user["id"], prize_id)
    await log_audit(user["id"], _admin_display_name(user), "update_prize", f"#{prize_id}: {prize.text}")
    return PrizeOut(
        id=prize.id,
        text=prize.text,
        icon=prize.icon,
        color=prize.color,
        position=prize.position,
        is_active=prize.is_active,
    )


@admin_router.delete("/prizes/{prize_id}")
async def delete_prize(
    prize_id: int,
    user: dict[str, Any] = Depends(require_admin),
) -> dict[str, str]:
    """Удалить приз."""
    async with async_session() as session:
        prize = await session.get(Prize, prize_id)
        if prize is None:
            raise HTTPException(status_code=404, detail="Приз не найден")

        # Проверяем минимум 2 активных сектора
        count_result = await session.execute(
            select(func.count(Prize.id)).where(
                Prize.is_active == True, Prize.id != prize_id  # noqa: E712
            )
        )
        active_count = count_result.scalar() or 0
        if prize.is_active and active_count < 2:
            raise HTTPException(
                status_code=400, detail="Минимум 2 активных сектора"
            )

        prize_text = prize.text
        logger.info("Админ %d удалил приз #%d (%s)", user["id"], prize_id, prize_text)
        await session.delete(prize)
        await session.commit()
    await log_audit(user["id"], _admin_display_name(user), "delete_prize", f"#{prize_id}: {prize_text}")
    return {"status": "ok"}


# ---- Управление доступом ----


@admin_router.get("/users", response_model=list[AdminOut])
async def get_admin_users(
    request: Request,
    _user: dict[str, Any] = Depends(require_admin),
) -> list[AdminOut]:
    """Список админов и просмотрщиков."""
    bot = request.app.state.bot
    async with async_session() as session:
        result = await session.execute(select(Admin).order_by(Admin.created_at))
        admins = result.scalars().all()

        # Подтягиваем инфо из Telegram для записей без имени
        for a in admins:
            if a.tg_first_name is None:
                try:
                    chat = await bot.get_chat(a.tg_user_id)
                    a.tg_username = chat.username
                    a.tg_first_name = chat.first_name or "—"
                except (Exception, BaseException) as exc:
                    logger.debug("Не удалось получить инфо для %d: %s", a.tg_user_id, exc)
        await session.commit()

    return [
        AdminOut(
            id=a.id,
            tg_user_id=a.tg_user_id,
            tg_username=a.tg_username,
            tg_first_name=a.tg_first_name,
            role=a.role,
            added_by=a.added_by,
            created_at=a.created_at.isoformat() if a.created_at else "",
        )
        for a in admins
    ]


@admin_router.post("/users", response_model=AdminOut)
async def create_admin_user(
    data: AdminCreate,
    request: Request,
    user: dict[str, Any] = Depends(require_admin),
) -> AdminOut:
    """Добавить админа / просмотрщика."""
    if data.role not in ("admin", "viewer"):
        raise HTTPException(status_code=400, detail="Роль должна быть admin или viewer")

    # Пробуем получить информацию о пользователе из Telegram
    tg_username: str | None = None
    tg_first_name: str | None = None
    try:
        bot = request.app.state.bot
        chat = await bot.get_chat(data.tg_user_id)
        tg_username = chat.username
        tg_first_name = chat.first_name
    except (Exception, BaseException) as exc:
        logger.debug("Не удалось получить инфо для Telegram ID %d: %s", data.tg_user_id, exc)

    async with async_session() as session:
        admin = Admin(
            tg_user_id=data.tg_user_id,
            tg_username=tg_username,
            tg_first_name=tg_first_name,
            role=data.role,
            added_by=user["id"],
        )
        session.add(admin)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(status_code=409, detail="Пользователь уже существует")
        await session.refresh(admin)

    logger.info("Админ %d добавил пользователя %d (роль=%s)", user["id"], data.tg_user_id, data.role)
    await log_audit(user["id"], _admin_display_name(user), "add_user", f"tg_id={data.tg_user_id}, role={data.role}")
    return AdminOut(
        id=admin.id,
        tg_user_id=admin.tg_user_id,
        tg_username=admin.tg_username,
        tg_first_name=admin.tg_first_name,
        role=admin.role,
        added_by=admin.added_by,
        created_at=admin.created_at.isoformat() if admin.created_at else "",
    )


@admin_router.delete("/users/{admin_id}")
async def delete_admin_user(
    admin_id: int,
    user: dict[str, Any] = Depends(require_admin),
) -> dict[str, str]:
    """Удалить админа / просмотрщика."""
    async with async_session() as session:
        admin = await session.get(Admin, admin_id)
        if admin is None:
            raise HTTPException(status_code=404, detail="Запись не найдена")
        admin_info = f"tg_id={admin.tg_user_id}, role={admin.role}"
        logger.info("Админ %d удалил пользователя %d (роль=%s)", user["id"], admin.tg_user_id, admin.role)
        await session.delete(admin)
        await session.commit()
    await log_audit(user["id"], _admin_display_name(user), "delete_user", admin_info)
    return {"status": "ok"}
