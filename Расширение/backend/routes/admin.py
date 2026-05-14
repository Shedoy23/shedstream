"""
routes/admin.py — администрирование: пользователи, предметы, очки.

ARCH NOTE (Block 2 audit): этот файл — единственный route'ер использующий
`aiosqlite.connect(db.db_path)` напрямую (bypass pool). Причина: Row factory
(`conn.row_factory = aiosqlite.Row`) меняет state соединения, что mутирует
pool-connection и влияет на следующих пользователей pool'а.

Future migration path:
1. Заменить `r['column']` на `r[index]` в SELECT-обработке
2. Перейти на `db._connect()` (через pool)
3. Удалить `import aiosqlite` отсюда

Дополнительно: вся логика admin-routes должна перейти в database.py
helpers (`db.list_users(search, limit)`, `db.update_user_points`, etc.) —
сейчас raw SQL прямо в endpoint'ах. Это тоже Block 2 follow-up task.
"""
import aiosqlite
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from config import sanitize_username
from dependencies import get_bot, get_db, require_admin

router = APIRouter()


@router.get("/api/admin/dev/jwt")
async def admin_dev_jwt(
    username: str = Query("shedoy23", description="Логин для preview"),
    minutes: int = Query(60, description="Срок жизни токена в минутах"),
    _admin: str = Depends(require_admin),
):
    """Выдать валидный Twitch Extension JWT для standalone-preview расширения
    без необходимости поднимать live-стрим.

    Use case: открыть https://shedoy23.ru/frontend/extension.html?dev_jwt=<TOKEN>
    в браузере → extension работает как будто загружен через Twitch helper.

    SECURITY: только admin. JWT короткоживущий (default 60 минут). Подписывается
    тем же TWITCH_EXTENSION_SECRET что и реальные Twitch tokens — поэтому
    backend принимает токен legitimately, никакого специального bypass нет.
    """
    import base64
    import time
    import jwt as _jwt
    from config import TWITCH_EXTENSION_SECRET, CHANNEL_POINTS_CONFIG

    if not TWITCH_EXTENSION_SECRET:
        return {"success": False, "message": "TWITCH_EXTENSION_SECRET не настроен"}

    uname = sanitize_username(username)
    if not uname:
        return {"success": False, "message": "Неверный username"}

    broadcaster_id = str(CHANNEL_POINTS_CONFIG.get("broadcaster_id") or "")
    if not broadcaster_id:
        return {"success": False, "message": "TWITCH_BROADCASTER_ID не настроен"}

    # Decode base64-encoded secret (Twitch стандарт)
    secret_b64 = TWITCH_EXTENSION_SECRET.replace("-", "+").replace("_", "/")
    padding = 4 - len(secret_b64) % 4
    if padding != 4:
        secret_b64 += "=" * padding
    secret_bytes = base64.b64decode(secret_b64)

    payload = {
        "channel_id":          broadcaster_id,
        "user_id":             broadcaster_id,
        "sub":                 uname,
        "role":                "broadcaster",
        "opaque_user_id":      f"U{broadcaster_id}",
        "exp":                 int(time.time()) + max(1, min(minutes, 1440)) * 60,
    }
    token = _jwt.encode(payload, secret_bytes, algorithm="HS256")

    preview_url = (
        f"https://shedoy23.ru/frontend/extension.html?dev_jwt={token}&dev_user={uname}"
    )
    return {
        "success":      True,
        "token":        token,
        "preview_url":  preview_url,
        "expires_in":   payload["exp"] - int(time.time()),
        "username":     uname,
    }


@router.get("/admin", response_class=HTMLResponse)
async def admin_panel(_admin: str = Depends(require_admin)):
    """Админ-панель"""
    try:
        with open("../admin/admin.html", "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "Создайте admin/admin.html"


@router.post("/api/admin/drop")
async def admin_force_drop(_admin: str = Depends(require_admin)):
    """Принудительный дроп"""
    return await get_bot().force_drop()


@router.get("/api/admin/stats")
async def admin_stats(_admin: str = Depends(require_admin)):
    """Статистика для админки"""
    return await get_db().get_stats()


@router.get("/api/admin/users")
async def admin_get_users(
    search: str = "",
    limit: int = 50,
    offset: int = 0,
    _admin: str = Depends(require_admin),
):
    """Список всех пользователей с поиском"""
    db          = get_db()
    safe_search = sanitize_username(search) if search else ""
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        if safe_search:
            cursor = await conn.execute("""
                SELECT username, points, is_afk, last_seen, join_time
                FROM viewers WHERE username LIKE ?
                ORDER BY points DESC LIMIT ? OFFSET ?
            """, (f"%{safe_search}%", limit, offset))
        else:
            cursor = await conn.execute("""
                SELECT username, points, is_afk, last_seen, join_time
                FROM viewers ORDER BY points DESC LIMIT ? OFFSET ?
            """, (limit, offset))
        rows    = await cursor.fetchall()
        cursor2 = await conn.execute("SELECT COUNT(*) FROM viewers")
        total   = (await cursor2.fetchone())[0]
    return {"users": [dict(r) for r in rows], "total": total}


@router.get("/api/admin/user/{username}")
async def admin_get_user(username: str, _admin: str = Depends(require_admin)):
    """Детали пользователя"""
    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("SELECT * FROM viewers WHERE username = ?", (username,))
        user   = await cursor.fetchone()
        if not user:
            return {"error": "Пользователь не найден"}

        cursor = await conn.execute("""
            SELECT i.display_name, i.emoji, i.rarity, inv.quantity
            FROM inventory inv JOIN items i ON inv.item_id = i.id
            WHERE inv.username = ?
        """, (username,))
        inventory = [dict(r) for r in await cursor.fetchall()]

        cursor = await conn.execute(
            "SELECT pawn_name, is_alive, health, world_name FROM rimworld_pawns WHERE username = ?",
            (username,))
        pawn = await cursor.fetchone()

    return {
        "user":      dict(user),
        "inventory": inventory,
        "pawn":      dict(pawn) if pawn else None,
    }


@router.post("/api/admin/points")
async def admin_adjust_points(request: Request, _admin: str = Depends(require_admin)):
    """Выдать/забрать очки"""
    data     = await request.json()
    username = data.get("username")
    amount   = int(data.get("amount", 0))
    action   = data.get("action", "add")  # add / remove / set

    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute("SELECT points FROM viewers WHERE username = ?", (username,))
        row    = await cursor.fetchone()
        if not row:
            return {"success": False, "message": "Пользователь не найден"}
        current = row[0]

    if action == "add":
        await db.add_points(username, amount)
        msg = f"+{amount}💎 → {current + amount}💎"
    elif action == "remove":
        await db.remove_points(username, amount)
        msg = f"-{amount}💎 → {max(0, current - amount)}💎"
    elif action == "set":
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("UPDATE viewers SET points = ? WHERE username = ?", (amount, username))
            await conn.commit()
        msg = f"Установлено {amount}💎"
    else:
        return {"success": False, "message": "Неверный action"}

    return {"success": True, "message": msg}


@router.post("/api/admin/transfer")
async def admin_transfer_points(request: Request, _admin: str = Depends(require_admin)):
    """Перевод очков между пользователями"""
    data      = await request.json()
    from_user = data.get("from_user")
    to_user   = data.get("to_user")
    amount    = int(data.get("amount", 0))
    if amount <= 0:
        return {"success": False, "message": "Сумма должна быть больше 0"}

    db          = get_db()
    from_points = await db.get_points(from_user)
    if from_points is None:
        return {"success": False, "message": f"{from_user} не найден"}
    to_points = await db.get_points(to_user)
    if to_points is None:
        return {"success": False, "message": f"{to_user} не найден"}
    if from_points < amount:
        return {"success": False, "message": f"У {from_user} только {from_points}💎"}

    if not await db.remove_points(from_user, amount):
        return {"success": False, "message": f"У {from_user} недостаточно очков"}
    await db.add_points(to_user, amount)
    return {"success": True, "message": f"💸 {from_user} → {to_user}: {amount}💎"}


@router.get("/api/admin/items")
async def admin_get_items(_admin: str = Depends(require_admin)):
    """Список всех предметов"""
    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT id, name, display_name, emoji, rarity, value FROM items ORDER BY rarity, name")
        rows = await cursor.fetchall()
    return {"items": [dict(r) for r in rows]}


@router.post("/api/admin/item/give")
async def admin_give_item(request: Request, _admin: str = Depends(require_admin)):
    """Выдать предмет пользователю"""
    data     = await request.json()
    username = data.get("username")
    item_id  = int(data.get("item_id"))
    quantity = int(data.get("quantity", 1))

    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute("SELECT display_name FROM items WHERE id = ?", (item_id,))
        item   = await cursor.fetchone()
        if not item:
            return {"success": False, "message": "Предмет не найден"}
        from dependencies import resolve_channel_id_or_default  # admin endpoint без JWT — TODO M4.4: per-channel admin UI
        channel_id = resolve_channel_id_or_default()
        await conn.execute("""
            INSERT INTO inventory (channel_id, username, item_id, quantity)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(channel_id, username, item_id) DO UPDATE SET quantity = quantity + ?
        """, (channel_id, username, item_id, quantity, quantity))
        await conn.commit()
    return {"success": True, "message": f"Выдано {item[0]} x{quantity} → {username}"}


@router.post("/api/admin/item/remove")
async def admin_remove_item(request: Request, _admin: str = Depends(require_admin)):
    """Забрать предмет у пользователя"""
    data     = await request.json()
    username = data.get("username")
    item_id  = int(data.get("item_id"))
    quantity = int(data.get("quantity", 1))

    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute(
            "SELECT quantity, display_name FROM inventory inv "
            "JOIN items i ON inv.item_id = i.id "
            "WHERE inv.username = ? AND inv.item_id = ?",
            (username, item_id))
        row = await cursor.fetchone()
        if not row:
            return {"success": False, "message": "Предмет не найден в инвентаре"}
        cur_qty, name = row
        if cur_qty <= quantity:
            await conn.execute(
                "DELETE FROM inventory WHERE username = ? AND item_id = ?", (username, item_id))
        else:
            await conn.execute(
                "UPDATE inventory SET quantity = quantity - ? WHERE username = ? AND item_id = ?",
                (quantity, username, item_id))
        await conn.commit()
    return {"success": True, "message": f"Забрано {name} x{quantity} у {username}"}


# ── Блок 1 архитектурной прокачки: DB health & visibility ────────────────────

@router.get("/api/admin/db/health")
async def admin_db_health(_admin: str = Depends(require_admin)):
    """Снимок состояния БД для visibility. Видим перед тем как горит.

    Returns:
      {
        db_size_mb, wal_size_mb,
        tables: [{table, row_count, approx_bytes}, ...],
        top_channels_by_viewers: [{channel_id, login, tier, viewers}, ...],
        wal_checkpoint_now: {mode, busy, log_pages, checkpointed_pages} | null
      }

    Полезно проверять:
    - wal_size_mb > 50 MB → checkpoint застрял (PASSIVE не успевает; писать
      RESTART/TRUNCATE)
    - top_channels первого канала >> остальных → возможный abuse
    - tables top-3 несбалансированы → может не быть индекса
    """
    db = get_db()
    db_bytes = await db.get_db_size_bytes()
    wal_bytes = await db.get_wal_size_bytes()
    tables = await db.get_table_sizes()
    top_channels = await db.get_per_channel_record_counts(top=10)
    # Сразу запустить PASSIVE checkpoint — visibility + maintenance в одном.
    cp_stats = await db.wal_checkpoint("PASSIVE")
    return {
        "db_size_mb": round(db_bytes / 1024 / 1024, 2),
        "wal_size_mb": round(wal_bytes / 1024 / 1024, 2),
        "tables": tables[:30],  # топ-30, остальные малозначительны
        "top_channels_by_viewers": top_channels,
        "wal_checkpoint_now": cp_stats,
    }


@router.post("/api/admin/db/checkpoint")
async def admin_db_checkpoint(
    mode: str = "PASSIVE",
    _admin: str = Depends(require_admin),
):
    """Принудительный WAL checkpoint. mode = PASSIVE|FULL|RESTART|TRUNCATE.

    TRUNCATE — после backup'а раз в сутки чтобы WAL не рос indefinitely.
    Использовать осторожно — RESTART/TRUNCATE могут блокировать writers.
    """
    return {"checkpoint": await get_db().wal_checkpoint(mode)}
