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


def promo_values_error(points: int, max_uses: int, item_def: str = None) -> str:
    """Reject codes that charge a use without a reward or hide a bad limit."""
    if points < 0:
        return "Очки не могут быть отрицательными"
    if max_uses < 0:
        return "Лимит применений не может быть отрицательным (0 = без лимита)"
    if points == 0 and not item_def:
        return "Укажи награду: очки или предмет"
    return ""


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

            item_id = None
            if item_def:
                icur = await conn.execute("SELECT id FROM items WHERE name = ?", (item_def,))
                irow = await icur.fetchone()
                item_id = irow[0] if irow else None
            if points <= 0 and item_id is None:
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "❌ У промокода нет действующей награды"}

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
            # Награда — В ТОЙ ЖЕ транзакции, что и запись use (иначе use записан, а
            # add_points/give_item могли не доехать → "уже использован" без награды).
            reward_parts = []
            if points > 0:
                await db.add_points_tx(conn, username, points, channel_id)
                reward_parts.append(f"{points}💎")
            if item_id is not None:
                await conn.execute(
                    "INSERT INTO inventory (channel_id, username, item_id, quantity) VALUES (?, ?, ?, 1) "
                    "ON CONFLICT(channel_id, username, item_id) DO UPDATE SET quantity = quantity + 1",
                    (channel_id, username.lower(), item_id))
                reward_parts.append(f"предмет «{item_name or item_def}»")
            await conn.commit()
        except Exception:
            await conn.execute("ROLLBACK")
            return {"success": False, "message": "Ошибка активации, попробуй ещё раз"}

    reward_str = " и ".join(reward_parts) if reward_parts else "бонус"
    return {"success": True, "message": f"✅ Промокод активирован! Ты получил: {reward_str}"}


@router.get("/api/admin/promocodes")
async def admin_get_promos(channel_id: int = 0, _admin: str = Depends(require_admin)):
    if channel_id == 0:
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
    try:
        data = await request.json()
    except Exception:
        return {"success": False, "message": "Ожидается JSON"}
    if not isinstance(data, dict):
        return {"success": False, "message": "Ожидается JSON-объект"}
    code      = str(data.get("code", "")).strip().upper()
    try:
        points = int(data.get("points", 0))
        max_uses = int(data.get("max_uses", 1))
    except (TypeError, ValueError):
        return {"success": False, "message": "Очки и лимит — числа"}
    item_def  = str(data.get("item_def") or "").strip() or None
    item_name = str(data.get("item_name") or "").strip() or None
    if not code:
        return {"success": False, "message": "Укажи код"}
    if error := promo_values_error(points, max_uses, item_def):
        return {"success": False, "message": error}

    channel_id = data.get("channel_id") or resolve_channel_id_or_default()
    db = get_db()
    async with db._connect() as conn:
        if item_def:
            cur = await conn.execute("SELECT 1 FROM items WHERE name=?", (item_def,))
            if not await cur.fetchone():
                return {"success": False, "message": "Предмет не найден в каталоге"}
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
async def admin_delete_promo(promo_id: int, channel_id: int = 0, _admin: str = Depends(require_admin)):
    if channel_id == 0:
        channel_id = resolve_channel_id_or_default()
    db = get_db()
    async with db._connect() as conn:
        await conn.execute(
            "DELETE FROM promocodes WHERE channel_id = ? AND id = ?", (channel_id, promo_id))
        await conn.commit()
    return {"success": True}
