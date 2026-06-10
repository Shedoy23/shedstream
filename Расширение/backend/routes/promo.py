"""
routes/promo.py — промокоды (активация и управление через админку).
"""
import sqlite3

from fastapi import APIRouter, Depends, Request

from config import sanitize_username
from dependencies import (
    get_bot,
    get_db,
    require_admin,
    require_jwt_user,
    require_stream_live,
    resolve_channel_id_or_default,
)

router = APIRouter()


@router.post("/api/promo/use")
async def use_promo(request: Request):
    """Активировать промокод"""
    if err := await require_stream_live():
        return err
    # 2026-06-07 SEC — username/channel из подписанного JWT, НЕ из body.
    # Раньше брали data["username"] без JWT → любой redeem'ил промо за любого
    # и сжигал лимит кода. require_jwt_user также выставляет channel ContextVar.
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "Авторизуйся через Twitch"}
    username, channel_id = auth

    data = await request.json()
    code = str(data.get("code", "")).strip().upper()
    if not code:
        return {"success": False, "message": "Неверные параметры"}

    await get_bot().touch_viewer(username, channel_id)

    db = get_db()
    async with db._connect() as conn:
        try:
            await conn.execute("BEGIN IMMEDIATE")

            c = await conn.execute(
                "SELECT id, points, item_def, item_name, max_uses, uses FROM promocodes "
                "WHERE channel_id = ? AND code = ?",
                (channel_id, code))
            row = await c.fetchone()
            if not row:
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "❌ Промокод не существует"}

            pid, points, item_def, item_name, max_uses, uses = row
            if max_uses > 0 and uses >= max_uses:
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "❌ Промокод уже исчерпан"}

            c2 = await conn.execute(
                "SELECT id FROM promo_uses WHERE channel_id = ? AND code = ? AND username = ?",
                (channel_id, code, username))
            if await c2.fetchone():
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "❌ Ты уже использовал этот промокод"}

            await conn.execute("UPDATE promocodes SET uses = uses + 1 WHERE id = ?", (pid,))
            await conn.execute(
                "INSERT INTO promo_uses (channel_id, code, username) VALUES (?,?,?)",
                (channel_id, code, username))
            await conn.commit()
        except Exception:
            await conn.execute("ROLLBACK")
            return {"success": False, "message": "Ошибка активации, попробуй ещё раз"}

    # 2026-06-06 FIX — channel_id явно (как в touch_viewer): эти вызовы ВНЕ try,
    # а add_points/give_item делают strict resolve_channel_id → без channel_id
    # роняли 500 ПОСЛЕ коммита use → "ошибка", а use уже записан → повтор "уже
    # использован". (+ give_item: 3-й позиционный арг = quantity, передавали имя.)
    reward_parts = []
    if points > 0:
        await db.add_points(username, points, channel_id=channel_id)
        reward_parts.append(f"{points}💎")
    if item_def:
        await db.give_item(username, item_def, 1, channel_id=channel_id)
        reward_parts.append(f"предмет «{item_name or item_def}»")

    reward_str = " и ".join(reward_parts) if reward_parts else "бонус"
    return {"success": True, "message": f"✅ Промокод активирован! Ты получил: {reward_str}"}


@router.get("/api/admin/promocodes")
async def admin_get_promos(_admin: str = Depends(require_admin)):
    channel_id = resolve_channel_id_or_default()
    db = get_db()
    async with db._connect() as conn:
        c = await conn.execute(
            "SELECT id, code, points, item_name, max_uses, uses, created_at "
            "FROM promocodes WHERE channel_id = ? ORDER BY id DESC",
            (channel_id,))
        rows = await c.fetchall()
    return {"promocodes": [
        {"id": r[0], "code": r[1], "points": r[2], "item_name": r[3],
         "max_uses": r[4], "uses": r[5], "created_at": r[6]}
        for r in rows
    ]}


@router.post("/api/admin/promocodes/create")
async def admin_create_promo(request: Request, _admin: str = Depends(require_admin)):
    data      = await request.json()
    code      = str(data.get("code", "")).strip().upper()
    points    = int(data.get("points", 0))
    item_def  = data.get("item_def", "") or None
    item_name = data.get("item_name", "") or None
    max_uses  = int(data.get("max_uses", 1))
    if not code:
        return {"success": False, "message": "Укажи код"}

    channel_id = resolve_channel_id_or_default()
    db = get_db()
    async with db._connect() as conn:
        try:
            await conn.execute(
                "INSERT INTO promocodes (channel_id, code, points, item_def, item_name, max_uses) "
                "VALUES (?,?,?,?,?,?)",
                (channel_id, code, points, item_def, item_name, max_uses))
            await conn.commit()
        except sqlite3.IntegrityError:
            return {"success": False, "message": "Такой промокод уже существует"}
        except Exception as e:
            return {"success": False, "message": f"Ошибка создания промокода: {e}"}
    return {"success": True, "message": f"✅ Промокод {code} создан"}


@router.delete("/api/admin/promocodes/{promo_id}")
async def admin_delete_promo(promo_id: int, _admin: str = Depends(require_admin)):
    channel_id = resolve_channel_id_or_default()
    db = get_db()
    async with db._connect() as conn:
        await conn.execute(
            "DELETE FROM promocodes WHERE channel_id = ? AND id = ?", (channel_id, promo_id))
        await conn.commit()
    return {"success": True}
