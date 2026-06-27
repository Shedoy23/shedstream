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


@router.post("/api/admin/module/issue-token")
async def admin_issue_module_token(
    request: Request,
    _admin: str = Depends(require_admin),
):
    """Admin: выдать module-token для C# мода / connector'а.

    Body: {"module_id": "bannerlord", "channel_id": 98319857}
    Returns: {token, channel_id, module_id, expires_in}

    Альтернатива к /api/streamer/module-token (session cookie). Use case —
    quick test mode без поднятия web-dashboard auth flow. Streamer руками
    copy-paste'ит token в config.json своего мода.

    Token подписан MODULE_TOKEN_SECRET (HMAC-SHA256), TTL 30 дней.
    """
    data = await request.json()
    module_id = (data.get("module_id") or "").strip().lower()
    try:
        channel_id = int(data.get("channel_id", 0))
    except (TypeError, ValueError):
        return {"success": False, "message": "channel_id должен быть числом"}

    if not module_id or not module_id.replace("_", "").replace(".", "").isalnum():
        return {"success": False, "message": "Неверный module_id"}
    if channel_id <= 0:
        return {"success": False, "message": "channel_id обязателен"}

    # Проверка что module зарегистрирован
    from modules._loader import get_module
    if get_module(module_id) is None:
        return {
            "success": False,
            "message": f"Module '{module_id}' не зарегистрирован в реестре",
        }

    from routes.streamer import issue_module_token, _MODULE_TOKEN_TTL
    token = issue_module_token(channel_id, module_id)

    return {
        "success":      True,
        "token":        token,
        "module_id":    module_id,
        "channel_id":   channel_id,
        "expires_in":   _MODULE_TOKEN_TTL,
        "instructions": (
            "Скопируй token в Modules/Shedoy23.BannerlordLink/config.json как "
            "module_token, также вставь channel_id. Restart Bannerlord — "
            "мод сможет слать events на /v1/module/<id>/events."
        ),
    }


@router.get("/api/admin/dev/jwt")
async def admin_dev_jwt(
    request: Request,
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

    role = "broadcaster" if request.query_params.get("role") == "broadcaster" else "viewer"
    payload = {
        "channel_id":          broadcaster_id,
        "user_id":             broadcaster_id,
        "sub":                 uname,
        "role":                role,
        "opaque_user_id":      f"U{broadcaster_id}",
        "exp":                 int(time.time()) + max(1, min(minutes, 1440)) * 60,
    }
    token = _jwt.encode(payload, secret_bytes, algorithm="HS256")

    # Pre-populate login cache — иначе resolve_jwt_login() пустой и
    # require_jwt_user() вернёт None → backend ответит "unauthorized".
    # Cache обычно заполняется через /api/whoami на первом юзер-логине;
    # preview-mode минует этот flow, поэтому injecting вручную.
    from dependencies import cache_twitch_login
    cache_twitch_login(
        user_id=broadcaster_id,
        opaque_id=f"U{broadcaster_id}",
        login=uname,
    )

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


# 2026-06-14 (audit): POST /api/admin/drop удалён — админка стала read-only
# (наблюдательной); god-mode «раздать предметы всем» убран.
# См. docs/SECURITY_AUDIT_2026-06-14.md.


@router.get("/api/admin/stats")
async def admin_stats(_admin: str = Depends(require_admin)):
    """Статистика для админки"""
    return await get_db().get_stats()


@router.get("/api/admin/bug-reports")
async def admin_bug_reports(_admin: str = Depends(require_admin)):
    """Read-only наблюдение: последние баг-репорты (!баг) канала."""
    from dependencies import resolve_channel_id_or_default
    channel_id = resolve_channel_id_or_default()
    db = get_db()
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT id, username, message, status, created_at FROM bug_reports "
            "WHERE channel_id=? ORDER BY created_at DESC LIMIT 30",
            (channel_id,))
        rows = await cur.fetchall()
    return {"reports": [
        {"id": r[0], "username": r[1], "message": r[2],
         "status": r[3], "created_at": r[4]} for r in rows]}


@router.get("/api/admin/feature-usage")
async def admin_feature_usage(_admin: str = Depends(require_admin)):
    """Read-only наблюдение: топ используемых фич за 7 дней (feature_usage)."""
    from dependencies import resolve_channel_id_or_default
    channel_id = resolve_channel_id_or_default()
    db = get_db()
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT feature_key, SUM(count) AS total FROM feature_usage "
            "WHERE channel_id=? AND day >= date('now','-7 days') "
            "GROUP BY feature_key ORDER BY total DESC LIMIT 15",
            (channel_id,))
        rows = await cur.fetchall()
    return {"features": [{"key": r[0], "total": r[1]} for r in rows]}


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


# 2026-06-14 (audit): POST /api/admin/points удалён — самый опасный эндпоинт
# (произвольная правка баланса любого зрителя). Админка read-only; владелец
# платформы наблюдает, а не влияет на экономику каналов. Редкие исправления —
# разовым залогированным скриптом. См. docs/SECURITY_AUDIT_2026-06-14.md.


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


# 2026-06-14 (audit): POST /api/admin/item/give + /api/admin/item/remove удалены —
# админка read-only; god-mode инвентаря (выдать/забрать предмет) убран.
# См. docs/SECURITY_AUDIT_2026-06-14.md.


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
