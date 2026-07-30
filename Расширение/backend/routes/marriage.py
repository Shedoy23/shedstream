"""
routes/marriage.py — браки между зрителями (создание, развод, семейный счёт).

Мультитенант: `marriages` и `marriage_proposals` имеют channel_id (добавлен M1).
КАЖДЫЙ запрос обязан скоупиться по channel_id — иначе зритель с тем же ником на
другом канале виден как «уже в браке» / читает чужие предложения (cross-tenant leak).
Источник channel_id: JWT (require_jwt_user) для зрительских ручек; resolve_default
для admin/публичных GET.
"""
from fastapi import APIRouter, Depends, Request

from config import FAMILY_CONFIG, sanitize_username
from dependencies import (
    get_db, require_admin, require_jwt_user, require_stream_live,
    resolve_channel_id_or_default,
)
from models import MarryRequest

router = APIRouter()

_AUTH_FAIL = {"success": False, "message": "❌ Требуется авторизация Twitch — открой расширение и войди"}


@router.post("/api/marriage/create")
async def create_marriage(request: MarryRequest, _admin: str = Depends(require_admin)):
    """Заключить брак (только для администратора)"""
    if err := await require_stream_live():
        return err
    if request.user1 == request.user2:
        return {"success": False, "message": "Нельзя жениться на себе"}

    channel_id = resolve_channel_id_or_default()
    db = get_db()
    async with db._connect() as conn:
        try:
            await conn.execute("BEGIN IMMEDIATE")
            for u in [request.user1, request.user2]:
                cursor = await conn.execute("""
                    SELECT id FROM marriages
                    WHERE channel_id = ? AND (user1 = ? OR user2 = ?) AND divorced_at IS NULL
                """, (channel_id, u, u))
                if await cursor.fetchone():
                    await conn.execute("ROLLBACK")
                    return {"success": False, "message": f"@{u} уже в браке"}

            # Phase 1.G (2026-05-10): family_balance колонка удалена в M8.
            # Sprint 5.20 fix (2026-05-20): убран family_balance из INSERT —
            # прод падал с OperationalError: no column named family_balance.
            await conn.execute("""
                INSERT INTO marriages (channel_id, user1, user2) VALUES (?, ?, ?)
            """, (channel_id, request.user1, request.user2))
            await conn.commit()
        except Exception:
            await conn.execute("ROLLBACK")
            return {"success": False, "message": "Ошибка создания брака, попробуй ещё раз"}

    return {
        "success": True,
        "message": f"💒 @{request.user1} и @{request.user2} теперь в браке!",
    }


@router.get("/api/marriage/status/{username}")
async def marriage_status(username: str, request: Request):
    """Статус брака (scoped по channel_id из JWT; без JWT → married:false).

    Phase 1.G (2026-05-10): family_balance + bonus_per_min удалены из ответа
    как financial pool (серая зона 2 в COMPLIANCE_REWORK_PLAN.md). Marriage
    теперь чисто social: статус, partner, эмодзи в чате/overlay.
    """
    auth = require_jwt_user(request)
    if not auth:
        return {"married": False}
    _, channel_id = auth
    db = get_db()
    async with db._connect() as conn:
        cursor = await conn.execute("""
            SELECT user1, user2 FROM marriages
            WHERE channel_id = ? AND (user1 = ? OR user2 = ?) AND divorced_at IS NULL
        """, (channel_id, username, username))
        row = await cursor.fetchone()
        if not row:
            return {"married": False}
        user1, user2 = row
        partner = user2 if username == user1 else user1
    return {
        "married": True,
        "partner": partner,
    }


@router.post("/api/marriage/divorce")
async def divorce(request: Request):
    """Развод — стоит 500💎 (sink крустиков; гейт от случайных разводов).

    Phase 1.G (2026-05-10): family_balance больше не используется —
    разводу нечего возвращать. Divorce_cost остаётся как символическая
    плата за подачу заявления.
    """
    if err := await require_stream_live():
        return err
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    sender, channel_id = auth

    from dependencies import get_bot
    await get_bot().touch_viewer(sender)

    DIVORCE_COST = FAMILY_CONFIG["divorce_cost"]
    db = get_db()
    # Атомарно: проверка брака + списание + divorced_at в одной транзакции (иначе
    # краш между списанием и divorced_at = деньги сняты, но брак не расторгнут).
    async with db._connect() as conn:
        try:
            await conn.execute("BEGIN IMMEDIATE")
            cursor = await conn.execute("""
                SELECT id FROM marriages
                WHERE channel_id = ? AND (user1 = ? OR user2 = ?) AND divorced_at IS NULL
            """, (channel_id, sender, sender))
            row = await cursor.fetchone()
            if not row:
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "Ты не в браке"}
            if not await db.remove_points_tx(conn, sender, DIVORCE_COST, channel_id):
                await conn.execute("ROLLBACK")
                return {"success": False, "message": f"Нужно {DIVORCE_COST}💎 для развода"}
            await conn.execute("""
                UPDATE marriages SET divorced_at = CURRENT_TIMESTAMP WHERE id = ? AND channel_id = ?
            """, (row[0], channel_id))
            await conn.commit()
        except Exception:
            await conn.execute("ROLLBACK")
            raise

    return {"success": True, "message": f"💔 Развод оформлен (-{DIVORCE_COST}💎)"}


# /api/marriage/withdraw удалён 2026-05-10 (Phase 1.G compliance rework —
# family_balance financial pool вырезан как P2P transfer proxy через marriage,
# серая зона 2 в COMPLIANCE_REWORK_PLAN.md). Семейный счёт refundится в личные
# крустики обоих супругов в миграции M8 (Phase 1.H).


@router.post("/api/marriage/propose")
async def marriage_propose(request: Request):
    """Отправить предложение руки и сердца"""
    if err := await require_stream_live():
        return err
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    sender, channel_id = auth

    from dependencies import get_bot
    await get_bot().touch_viewer(sender)

    data   = await request.json()
    target = sanitize_username(data.get("target", ""))
    if not target or sender == target:
        return {"success": False, "message": "Неверные параметры"}

    db = get_db()
    async with db._connect() as conn:
        for u in [sender, target]:
            cursor = await conn.execute("""
                SELECT id FROM marriages
                WHERE channel_id = ? AND (user1=? OR user2=?) AND divorced_at IS NULL
            """, (channel_id, u, u))
            if await cursor.fetchone():
                return {"success": False, "message": f"@{u} уже в браке"}
        await conn.execute("""
            DELETE FROM marriage_proposals WHERE channel_id=? AND from_user=? AND to_user=?
        """, (channel_id, sender, target))
        await conn.execute("""
            INSERT INTO marriage_proposals (channel_id, from_user, to_user) VALUES (?, ?, ?)
        """, (channel_id, sender, target))
        await conn.commit()

    return {"success": True, "message": f"💍 Предложение отправлено @{target}! Ждём ответа..."}


@router.post("/api/marriage/accept")
async def marriage_accept(request: Request):
    """Принять предложение руки и сердца"""
    if err := await require_stream_live():
        return err
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    sender, channel_id = auth

    from dependencies import get_bot
    await get_bot().touch_viewer(sender)

    db = get_db()
    async with db._connect() as conn:
        # 2026-07-31 (внешний аудит S-19). Без BEGIN IMMEDIATE два одновременных
        # «принять» (двойной клик) читали предложение и проверку «уже в браке»
        # ДО первой записи — и оба вставляли активный брак. Уникального
        # ограничения на активного участника в схеме нет, так что вторая строка
        # оставалась жить. Цена ошибки денежная: развод расторгает РОВНО ОДНУ
        # строку (`WHERE id = ?`) за 500💎, поэтому выпутаться из двойного брака
        # стоило зрителю два развода вместо одного.
        await conn.execute("BEGIN IMMEDIATE")
        cursor = await conn.execute("""
            SELECT from_user FROM marriage_proposals WHERE channel_id=? AND to_user=?
            ORDER BY created_at DESC LIMIT 1
        """, (channel_id, sender))
        row = await cursor.fetchone()
        if not row:
            await conn.execute("ROLLBACK")
            return {"success": False, "message": "Нет входящих предложений"}
        proposer = row[0]
        for u in [sender, proposer]:
            cursor2 = await conn.execute("""
                SELECT id FROM marriages
                WHERE channel_id=? AND (user1=? OR user2=?) AND divorced_at IS NULL
            """, (channel_id, u, u))
            if await cursor2.fetchone():
                await conn.execute("ROLLBACK")
                return {"success": False, "message": f"@{u} уже в браке"}
        # Phase 1.G (2026-05-10): family_balance удалена в M8.
        # Sprint 5.20 fix (2026-05-20): убран family_balance из INSERT.
        await conn.execute("""
            INSERT INTO marriages (channel_id, user1, user2) VALUES (?, ?, ?)
        """, (channel_id, proposer, sender))
        await conn.execute(
            "DELETE FROM marriage_proposals WHERE channel_id=? AND to_user=?",
            (channel_id, sender))
        await conn.commit()

    # 🎉 Свадьба — редкое событие, пишем в чат
    try:
        from dependencies import get_bot
        import asyncio as _asyncio
        _asyncio.create_task(get_bot().send_message(
            f"💒✨ СВАДЬБА! 💍 @{proposer} и @{sender} теперь муж и жена! "
            f"Совет да любовь 💕"
        ))
    except Exception as e:
        print(f"marriage chat error: {e}")

    return {
        "success": True,
        "message": f"💒 @{proposer} и @{sender} теперь в браке!",
    }


@router.post("/api/marriage/reject")
async def marriage_reject(request: Request):
    """Отклонить конкретное предложение руки и сердца.

    Sprint 5.20 (2026-05-20): добавлено для UX-симметрии с accept. Раньше
    зритель мог только принять или игнорировать — теперь явный reject
    DELETE'ит запись из marriage_proposals (от proposer'а к sender'у).
    """
    if err := await require_stream_live():
        return err
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    sender, channel_id = auth

    from dependencies import get_bot
    await get_bot().touch_viewer(sender)

    data = await request.json()
    from_user = sanitize_username(data.get("from_user", ""))
    if not from_user:
        return {"success": False, "message": "Неверные параметры"}

    db = get_db()
    async with db._connect() as conn:
        cursor = await conn.execute("""
            DELETE FROM marriage_proposals WHERE channel_id=? AND from_user=? AND to_user=?
        """, (channel_id, from_user, sender))
        await conn.commit()
        deleted = cursor.rowcount

    if not deleted:
        return {"success": False, "message": "Предложение не найдено"}
    return {"success": True, "message": f"💔 Предложение от @{from_user} отклонено"}


@router.get("/api/marriage/proposals/{username}")
async def get_proposals(username: str, request: Request):
    """Входящие предложения (scoped по channel_id из JWT)."""
    auth = require_jwt_user(request)
    if not auth:
        return {"proposals": []}
    # IDOR-fix (A3, 2026-07-02): свои входящие предложения — path {username}
    # игнорируем (раньше _,channel_id отбрасывал логин → читались чужие).
    login, channel_id = auth
    db       = get_db()
    async with db._connect() as conn:
        cursor = await conn.execute("""
            SELECT from_user FROM marriage_proposals WHERE channel_id=? AND to_user=?
            ORDER BY created_at DESC
        """, (channel_id, login))
        rows = await cursor.fetchall()
    return {"proposals": [r[0] for r in rows]}
