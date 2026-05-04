"""
routes/market.py — рынок предметов между зрителями.
"""
from datetime import datetime, timedelta, timezone

import aiosqlite
from fastapi import APIRouter, Request

from dependencies import get_bot, get_db, require_jwt_user, require_stream_live

router = APIRouter()

_AUTH_FAIL = {"success": False, "message": "❌ Требуется авторизация Twitch — открой расширение и войди"}

_MIN_PRICES = {
    "деревяшка": 10,
    "камень":    60,
    "амулет":    320,
    "корона":    2000,
}
_DURATION_SECONDS = 300  # 5 минут


@router.post("/api/market/list")
async def market_list_item(request: Request):
    """Выставить предмет на рынок"""
    if err := await require_stream_live():
        return err

    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth

    await get_bot().touch_viewer(username)

    data      = await request.json()
    item_name = (data.get("item_name") or "").lower().strip()
    price     = int(data.get("price") or 0)

    if not item_name:
        return {"success": False, "message": "Неверные параметры"}

    min_price = _MIN_PRICES.get(item_name)
    if min_price is None:
        return {"success": False, "message": f"Предмет '{item_name}' нельзя продать"}
    if price < min_price:
        return {"success": False, "message": f"Минимальная цена: {min_price}💎"}

    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute(
            "SELECT i.id, i.emoji, inv.quantity FROM inventory inv "
            "JOIN items i ON inv.item_id = i.id "
            "WHERE inv.username = ? AND i.name = ?",
            (username, item_name))
        row = await cursor.fetchone()
        if not row or row[2] < 1:
            return {"success": False, "message": f"У тебя нет {item_name}"}
        item_id, item_emoji, qty = row

        if qty == 1:
            await conn.execute(
                "DELETE FROM inventory WHERE username = ? AND item_id = ?", (username, item_id))
        else:
            await conn.execute(
                "UPDATE inventory SET quantity = quantity - 1 WHERE username = ? AND item_id = ?",
                (username, item_id))

        expires_at = (
            datetime.now(timezone.utc).replace(tzinfo=None)
            + timedelta(seconds=_DURATION_SECONDS)
        ).isoformat()
        await conn.execute(
            "INSERT INTO market_listings (seller, item_name, item_emoji, price, expires_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (username, item_name, item_emoji, price, expires_at))
        await conn.commit()

    return {"success": True, "message": f"✅ {item_emoji} {item_name.capitalize()} выставлен за {price}💎 на 5 минут"}


@router.get("/api/market")
async def market_get():
    """Список активных лотов"""
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    db  = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute(
            "SELECT id, seller, item_name, item_emoji, price, expires_at "
            "FROM market_listings WHERE expires_at > ? ORDER BY created_at DESC",
            (now,))
        rows = await cursor.fetchall()
    return {"listings": [
        {"id": r[0], "seller": r[1], "item_name": r[2], "item_emoji": r[3],
         "price": r[4], "expires_at": r[5]}
        for r in rows
    ]}


@router.post("/api/market/buy")
async def market_buy_item(request: Request):
    """Купить предмет с рынка"""
    if err := await require_stream_live():
        return err
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    sender, channel_id = auth

    await get_bot().touch_viewer(sender)

    data       = await request.json()
    listing_id = int(data.get("listing_id") or 0)
    if not listing_id:
        return {"success": False, "message": "Неверные параметры"}

    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        try:
            await conn.execute("BEGIN IMMEDIATE")

            cursor = await conn.execute(
                "SELECT id, seller, item_name, item_emoji, price, expires_at "
                "FROM market_listings WHERE id = ?",
                (listing_id,))
            row = await cursor.fetchone()
            if not row:
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "Лот не найден"}

            lid, seller, item_name, item_emoji, price, expires_at = row
            seller = (seller or "").lower().strip()

            if expires_at <= now:
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "Лот уже истёк"}
            if seller == sender:
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "Нельзя купить свой лот"}

            deduct_cur = await conn.execute(
                "UPDATE viewers SET points = points - ? WHERE username = ? AND points >= ?",
                (price, sender, price))
            if deduct_cur.rowcount == 0:
                await conn.execute("ROLLBACK")
                buyer_points = await db.get_points(sender)
                return {"success": False, "message": f"Нужно {price}💎, у тебя {buyer_points}💎"}

            await conn.execute(
                """
                INSERT INTO viewers (channel_id, username, points, last_seen, join_time, is_afk)
                VALUES (?, ?, ?, datetime('now'), datetime('now'), 0)
                ON CONFLICT(channel_id, username) DO UPDATE SET
                    points = points + excluded.points,
                    last_seen = datetime('now')
                """,
                (channel_id, seller, price))

            cursor2  = await conn.execute("SELECT id FROM items WHERE name = ?", (item_name,))
            item_row = await cursor2.fetchone()
            if not item_row:
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "Предмет из лота не найден"}

            await conn.execute(
                "INSERT INTO inventory (channel_id, username, item_id, quantity) VALUES (?, ?, ?, 1) "
                "ON CONFLICT(channel_id, username, item_id) DO UPDATE SET quantity = quantity + 1",
                (channel_id, sender, item_row[0]))

            del_cur = await conn.execute(
                "DELETE FROM market_listings WHERE id = ?", (lid,))
            if del_cur.rowcount == 0:
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "Лот уже куплен"}

            await conn.commit()
        except Exception:
            await conn.execute("ROLLBACK")
            raise

    return {"success": True,
            "message": f"✅ Куплено: {item_emoji} {item_name.capitalize()} за {price}💎 у @{seller}!"}


@router.post("/api/market/cancel")
async def market_cancel_listing(request: Request):
    """Отозвать свой лот (возврат предмета)"""
    if err := await require_stream_live():
        return err
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    sender, channel_id = auth

    await get_bot().touch_viewer(sender)

    data       = await request.json()
    listing_id = int(data.get("listing_id") or 0)

    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute(
            "SELECT seller, item_name FROM market_listings WHERE id = ?", (listing_id,))
        row = await cursor.fetchone()
        if not row:
            return {"success": False, "message": "Лот не найден"}
        if row[0] != sender:
            return {"success": False, "message": "Это не твой лот"}

        item_name = row[1]
        cursor2   = await conn.execute("SELECT id FROM items WHERE name = ?", (item_name,))
        item_row  = await cursor2.fetchone()
        if item_row:
            await conn.execute("""
                INSERT INTO inventory (channel_id, username, item_id, quantity) VALUES (?, ?, ?, 1)
                ON CONFLICT(channel_id, username, item_id) DO UPDATE SET quantity = quantity + 1
            """, (channel_id, sender, item_row[0]))
        await conn.execute("DELETE FROM market_listings WHERE id = ?", (listing_id,))
        await conn.commit()

    return {"success": True, "message": "↩️ Лот отозван, предмет возвращён"}
