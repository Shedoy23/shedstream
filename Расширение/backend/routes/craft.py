"""
routes/craft.py — крафт: 5 предметов → 1 следующего уровня.
"""
import asyncio
import random

from fastapi import APIRouter, Request

from config import sanitize_username
from dependencies import get_bot, get_db, require_stream_live

router = APIRouter()

_CRAFT = {
    "деревяшка": {"cost": 5, "result": "камень",  "emoji": "🪨"},
    "камень":    {"cost": 5, "result": "амулет",  "emoji": "🔮"},
    "амулет":    {"cost": 5, "result": "корона",  "emoji": "👑"},
}


@router.get("/api/craft/recipes")
async def craft_recipes():
    return {"recipes": [
        {"cost_item": k, "cost_qty": v["cost"], "result": v["result"], "result_emoji": v["emoji"]}
        for k, v in _CRAFT.items()
    ]}


@router.post("/api/craft")
async def craft_item(request: Request):
    if err := await require_stream_live():
        return err
    data      = await request.json()
    username  = (data.get("username") or "").lower().strip()
    item_name = (data.get("item_name") or "").lower().strip()
    if not username or not item_name:
        return {"success": False, "message": "Неверные параметры"}
    recipe = _CRAFT.get(item_name)
    if not recipe:
        return {"success": False, "message": f"Нет рецепта для «{item_name}»"}

    cost, result_name, emoji = recipe["cost"], recipe["result"], recipe["emoji"]
    db  = get_db()
    bot = get_bot()
    from dependencies import resolve_channel_id_or_default  # craft endpoint без JWT — TODO M4.4: добавить require_jwt_user
    channel_id = resolve_channel_id_or_default()
    await bot.touch_viewer(username, channel_id)

    try:
        async with db._connect() as conn:
            await conn.execute("BEGIN IMMEDIATE")

            cur = await conn.execute("SELECT id FROM items WHERE name=?", (item_name,))
            src = await cur.fetchone()
            if not src:
                await conn.execute("ROLLBACK")
                return {"success": False, "message": "Предмет не найден в базе"}

            cur      = await conn.execute("SELECT id FROM items WHERE name=?", (result_name,))
            res_item = await cur.fetchone()
            owned_result = 0
            if res_item:
                cur = await conn.execute(
                    "SELECT quantity FROM inventory WHERE username=? AND item_id=?",
                    (username, res_item[0]))
                row = await cur.fetchone()
                owned_result = row[0] if row else 0

            success_chance = db.calc_craft_chance(owned_result)

            cur = await conn.execute(
                "SELECT quantity FROM inventory WHERE username=? AND item_id=?",
                (username, src[0]))
            row = await cur.fetchone()
            qty = row[0] if row else 0
            if qty < cost:
                await conn.execute("ROLLBACK")
                return {"success": False, "message": f"Нужно {cost}× {item_name}, у тебя {qty}"}

            if qty == cost:
                await conn.execute(
                    "DELETE FROM inventory WHERE username=? AND item_id=?", (username, src[0]))
            else:
                await conn.execute(
                    "UPDATE inventory SET quantity=quantity-? WHERE username=? AND item_id=?",
                    (cost, username, src[0]))

            roll = random.randint(1, 100)
            if roll <= success_chance:
                cur = await conn.execute("SELECT id FROM items WHERE name=?", (result_name,))
                res = await cur.fetchone()
                if not res:
                    await conn.execute("ROLLBACK")
                    return {"success": False, "message": "Результат не найден в базе"}
                await conn.execute("""
                    INSERT INTO inventory (channel_id, username, item_id, quantity) VALUES (?,?,?,1)
                    ON CONFLICT(channel_id, username, item_id) DO UPDATE SET quantity=quantity+1
                """, (channel_id, username, res[0]))
                await conn.execute("""
                    INSERT INTO craft_stats (channel_id, username, item_type, crafted_count)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(channel_id, username, item_type) DO UPDATE SET crafted_count = crafted_count + 1
                """, (channel_id, username, item_name))
                await conn.commit()
                asyncio.create_task(bot.check_and_unlock_achievements(username, "craft"))
                return {"success": True, "chance": success_chance, "rolled": roll,
                        "message": f"✅ Успех! Скрафтил {emoji} {result_name}! (шанс {success_chance}%)"}
            else:
                await conn.execute("""
                    INSERT INTO craft_stats (channel_id, username, item_type, crafted_count)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(channel_id, username, item_type) DO UPDATE SET crafted_count = crafted_count + 1
                """, (channel_id, username, item_name))
                await conn.commit()
                return {"success": False, "chance": success_chance, "rolled": roll,
                        "message": f"❌ Крафт провалился! Материалы потеряны... (шанс был {success_chance}%)"}
    except Exception:
        return {"success": False, "message": "Ошибка крафта, попробуй ещё раз"}


@router.get("/api/craft/stats/{username}")
async def get_craft_stats(username: str):
    """Статистика крафта пользователя"""
    username = sanitize_username(username)
    if not username:
        return {"stats": []}

    db    = get_db()
    stats = []
    async with db._connect() as conn:
        for item_name, recipe in _CRAFT.items():
            result_name   = recipe["result"]
            crafted_count = await db.get_craft_count(username, item_name)

            cur      = await conn.execute("SELECT id FROM items WHERE name=?", (result_name,))
            res_item = await cur.fetchone()
            owned_result = 0
            if res_item:
                cur = await conn.execute(
                    "SELECT quantity FROM inventory WHERE username=? AND item_id=?",
                    (username, res_item[0]))
                row = await cur.fetchone()
                owned_result = row[0] if row else 0

            stats.append({
                "item":         item_name,
                "result":       result_name,
                "result_emoji": recipe["emoji"],
                "crafted":      crafted_count,
                "owned":        owned_result,
                "chance":       db.calc_craft_chance(owned_result),
            })
    return {"stats": stats}
