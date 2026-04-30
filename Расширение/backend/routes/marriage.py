"""
routes/marriage.py — браки между зрителями (создание, развод, семейный счёт).
"""
import aiosqlite
from fastapi import APIRouter, Depends, Request

from auth import verify_twitch_jwt
from config import FAMILY_CONFIG, sanitize_username, validate_username
from dependencies import get_db, require_admin, require_stream_live, resolve_jwt_login
from models import MarryRequest

router = APIRouter()


@router.post("/api/marriage/create")
async def create_marriage(request: MarryRequest, _admin: str = Depends(require_admin)):
    """Заключить брак (только для администратора)"""
    if err := await require_stream_live():
        return err
    if request.user1 == request.user2:
        return {"success": False, "message": "Нельзя жениться на себе"}

    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        try:
            await conn.execute("BEGIN IMMEDIATE")
            for u in [request.user1, request.user2]:
                cursor = await conn.execute("""
                    SELECT id FROM marriages
                    WHERE (user1 = ? OR user2 = ?) AND divorced_at IS NULL
                """, (u, u))
                if await cursor.fetchone():
                    await conn.execute("ROLLBACK")
                    return {"success": False, "message": f"@{u} уже в браке"}

            await conn.execute("""
                INSERT INTO marriages (user1, user2, family_balance) VALUES (?, ?, 0)
            """, (request.user1, request.user2))
            await conn.commit()
        except Exception:
            await conn.execute("ROLLBACK")
            return {"success": False, "message": "Ошибка создания брака, попробуй ещё раз"}

    return {
        "success": True,
        "message": f"💒 @{request.user1} и @{request.user2} теперь в браке! +15💎/мин за совместный просмотр",
    }


@router.get("/api/marriage/status/{username}")
async def marriage_status(username: str):
    """Статус брака"""
    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute("""
            SELECT user1, user2, family_balance FROM marriages
            WHERE (user1 = ? OR user2 = ?) AND divorced_at IS NULL
        """, (username, username))
        row = await cursor.fetchone()
        if not row:
            return {"married": False}
        user1, user2, balance = row
        partner = user2 if username == user1 else user1
    return {
        "married":      True,
        "partner":      partner,
        "balance":      balance,
        "bonus_per_min": FAMILY_CONFIG["bonus_per_min"],
    }


@router.post("/api/marriage/divorce")
async def divorce(request: Request):
    """Развод — стоит 500💎"""
    if err := await require_stream_live():
        return err
    jwt_result = verify_twitch_jwt(request)
    if jwt_result.get("status") == "invalid":
        return {"success": False, "message": "❌ Неверная авторизация Twitch"}
    if jwt_result.get("status") == "none":
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    sender = sanitize_username(resolve_jwt_login(jwt_result))
    if not sender or not validate_username(sender):
        return {"success": False, "message": "❌ Неверный отправитель"}

    from dependencies import get_bot
    await get_bot().touch_viewer(sender)

    DIVORCE_COST = FAMILY_CONFIG["divorce_cost"]
    db     = get_db()
    points = await db.get_points(sender)
    if points < DIVORCE_COST:
        return {"success": False, "message": f"Нужно {DIVORCE_COST}💎 для развода"}

    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute("""
            SELECT id FROM marriages
            WHERE (user1 = ? OR user2 = ?) AND divorced_at IS NULL
        """, (sender, sender))
        row = await cursor.fetchone()
    if not row:
        return {"success": False, "message": "Ты не в браке"}

    if not await db.remove_points(sender, DIVORCE_COST):
        return {"success": False, "message": f"Баланс упал — нужно {DIVORCE_COST}💎"}

    async with aiosqlite.connect(db.db_path) as conn:
        await conn.execute("""
            UPDATE marriages SET divorced_at = CURRENT_TIMESTAMP WHERE id = ?
        """, (row[0],))
        await conn.commit()

    return {"success": True, "message": f"💔 Развод оформлен (-{DIVORCE_COST}💎)"}


@router.post("/api/marriage/withdraw")
async def marriage_withdraw(request: Request):
    """Вывести средства из семейного счёта на личный"""
    if err := await require_stream_live():
        return err
    jwt_result = verify_twitch_jwt(request)
    if jwt_result.get("status") == "invalid":
        return {"success": False, "message": "❌ Неверная авторизация Twitch"}
    if jwt_result.get("status") == "none":
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    sender = sanitize_username(resolve_jwt_login(jwt_result))
    if not sender or not validate_username(sender):
        return {"success": False, "message": "❌ Неверный отправитель"}

    from dependencies import get_bot
    await get_bot().touch_viewer(sender)

    data = await request.json()
    try:
        amount = int(data.get("amount", 0))
    except (TypeError, ValueError):
        return {"success": False, "message": "Неверные параметры"}
    if amount <= 0:
        return {"success": False, "message": "Неверные параметры"}

    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        try:
            await conn.execute("BEGIN IMMEDIATE")
            cursor = await conn.execute("""
                SELECT id, family_balance FROM marriages
                WHERE (user1 = ? OR user2 = ?) AND divorced_at IS NULL
            """, (sender, sender))
            row = await cursor.fetchone()
            if not row:
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "Ты не в браке"}
            mid, balance = row
            if balance < amount:
                await conn.execute("ROLLBACK")
                return {"success": False, "message": f"В семейном счёте только {balance}💎"}
            await conn.execute(
                "UPDATE marriages SET family_balance = family_balance - ? WHERE id = ?",
                (amount, mid))
            await conn.commit()
        except Exception:
            await conn.execute("ROLLBACK")
            return {"success": False, "message": "Ошибка вывода, попробуй ещё раз"}

    await db.add_points(sender, amount)
    return {"success": True, "message": f"💸 Выведено {amount}💎 на личный счёт!"}


@router.post("/api/marriage/propose")
async def marriage_propose(request: Request):
    """Отправить предложение руки и сердца"""
    if err := await require_stream_live():
        return err
    jwt_result = verify_twitch_jwt(request)
    if jwt_result.get("status") == "invalid":
        return {"success": False, "message": "❌ Неверная авторизация Twitch"}
    if jwt_result.get("status") == "none":
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    sender = sanitize_username(resolve_jwt_login(jwt_result))
    if not sender or not validate_username(sender):
        return {"success": False, "message": "❌ Неверный отправитель"}

    from dependencies import get_bot
    await get_bot().touch_viewer(sender)

    data   = await request.json()
    target = sanitize_username(data.get("target", ""))
    if not target or sender == target:
        return {"success": False, "message": "Неверные параметры"}

    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        for u in [sender, target]:
            cursor = await conn.execute("""
                SELECT id FROM marriages WHERE (user1=? OR user2=?) AND divorced_at IS NULL
            """, (u, u))
            if await cursor.fetchone():
                return {"success": False, "message": f"@{u} уже в браке"}
        await conn.execute("""
            DELETE FROM marriage_proposals WHERE from_user=? AND to_user=?
        """, (sender, target))
        await conn.execute("""
            INSERT INTO marriage_proposals (from_user, to_user) VALUES (?, ?)
        """, (sender, target))
        await conn.commit()

    return {"success": True, "message": f"💍 Предложение отправлено @{target}! Ждём ответа..."}


@router.post("/api/marriage/accept")
async def marriage_accept(request: Request):
    """Принять предложение руки и сердца"""
    if err := await require_stream_live():
        return err
    jwt_result = verify_twitch_jwt(request)
    if jwt_result.get("status") == "invalid":
        return {"success": False, "message": "❌ Неверная авторизация Twitch"}
    if jwt_result.get("status") == "none":
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    sender = sanitize_username(resolve_jwt_login(jwt_result))
    if not sender or not validate_username(sender):
        return {"success": False, "message": "❌ Неверный отправитель"}

    from dependencies import get_bot
    await get_bot().touch_viewer(sender)

    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute("""
            SELECT from_user FROM marriage_proposals WHERE to_user=?
            ORDER BY created_at DESC LIMIT 1
        """, (sender,))
        row = await cursor.fetchone()
        if not row:
            return {"success": False, "message": "Нет входящих предложений"}
        proposer = row[0]
        for u in [sender, proposer]:
            cursor2 = await conn.execute("""
                SELECT id FROM marriages WHERE (user1=? OR user2=?) AND divorced_at IS NULL
            """, (u, u))
            if await cursor2.fetchone():
                return {"success": False, "message": f"@{u} уже в браке"}
        await conn.execute("""
            INSERT INTO marriages (user1, user2, family_balance) VALUES (?, ?, 0)
        """, (proposer, sender))
        await conn.execute("DELETE FROM marriage_proposals WHERE to_user=?", (sender,))
        await conn.commit()

    # 🎉 Свадьба — редкое событие, пишем в чат
    try:
        from dependencies import get_bot
        import asyncio as _asyncio
        _asyncio.create_task(get_bot().send_message(
            f"💒✨ СВАДЬБА! 💍 @{proposer} и @{sender} теперь муж и жена! "
            f"Совет да любовь 💕 (+15💎/мин за совместный просмотр)"
        ))
    except Exception as e:
        print(f"marriage chat error: {e}")

    return {
        "success": True,
        "message": f"💒 @{proposer} и @{sender} теперь в браке! +15💎/мин за совместный просмотр",
    }


@router.get("/api/marriage/proposals/{username}")
async def get_proposals(username: str):
    """Входящие предложения"""
    username = sanitize_username(username)
    db       = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute("""
            SELECT from_user FROM marriage_proposals WHERE to_user=?
            ORDER BY created_at DESC
        """, (username,))
        rows = await cursor.fetchall()
    return {"proposals": [r[0] for r in rows]}
