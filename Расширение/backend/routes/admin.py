"""
routes/admin.py — администрирование: пользователи, предметы, очки.

tenant-lint: skip-file — admin panel is a single platform-owner surface
(require_admin = one HTTP-Basic credential, read-only since the 2026-06-14 audit);
its cross-channel viewer/inventory/pawn reads are intentional, not a tenant leak.

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


@router.get("/api/admin/channels")
async def admin_list_channels(_admin: str = Depends(require_admin)):
    """M99: кто зарегистрировался и кто ждёт подключения.

    Первое, что нужно после одобрения Twitch: увидеть заявки. Без этого
    «ожидающий» стример виден только в логе, то есть практически невидим.
    """
    rows = await get_db().list_channels()
    pending = [r for r in rows if not r.get("approved")]
    return {
        "success": True,
        "total": len(rows),
        "pending_count": len(pending),
        "channels": rows,
    }


@router.post("/api/admin/approve-channel")
async def admin_approve_channel(
    request: Request,
    _admin: str = Depends(require_admin),
):
    """M99: открыть каналу ворота (или закрыть обратно).

    Body: {"channel_id": 123, "approved": true}

    Кэш обновляем сразу — иначе одобрение подействовало бы только после
    рестарта прода, а рестарт посреди стрима рвёт зрителям соединение.
    """
    from dependencies import mark_channel_approved
    try:
        body = await request.json()
    except Exception:
        return {"success": False, "message": "Ожидается JSON"}

    try:
        channel_id = int(body.get("channel_id"))
    except (TypeError, ValueError):
        return {"success": False, "message": "Нужен channel_id (число)"}

    approved = bool(body.get("approved", True))
    if not await get_db().set_channel_approved(channel_id, approved):
        return {"success": False,
                "message": f"Канал {channel_id} не найден в реестре"}

    mark_channel_approved(channel_id, approved)

    # Одобрили — бот заходит в чат СЕЙЧАС, а не после рестарта бэкенда.
    # Периодический цикл сверки подхватил бы канал и сам, но его минута
    # приходится ровно на те первые минуты, когда новый стример смотрит на
    # молчащий чат и решает, что продукт не работает.
    if approved:
        row = await get_db().get_channel(channel_id)
        login = (row or {}).get("login")
        if login:
            try:
                from main import join_channel_now
                await join_channel_now(login)
            except Exception as e:
                # Не роняем одобрение из-за чата: цикл сверки догонит.
                print(f"⚠️ join_channel_now({login}) при одобрении: {e}")

    print(f"{'✅ ОДОБРЕН' if approved else '⛔ ЗАКРЫТ'} канал {channel_id} (админ)")
    return {"success": True, "channel_id": channel_id, "approved": approved}


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


@router.post("/api/admin/bug-reports/status")
async def admin_bug_report_status(request: Request, _admin: str = Depends(require_admin)):
    """Разработчик помечает багрепорт resolved/open. Триаж переехал сюда из
    стримерского дашборда 2026-07-02 (техбаги расширения чинит разработчик, не стример)."""
    from dependencies import resolve_channel_id_or_default
    channel_id = resolve_channel_id_or_default()
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        report_id = int(body.get("id"))
    except (TypeError, ValueError):
        return {"status": "invalid_id"}
    new_status = (body.get("status") or "").strip()
    if new_status not in ("open", "resolved"):
        return {"status": "invalid_status"}
    import bug_reports
    ok = await bug_reports.set_bug_status(channel_id, report_id, new_status)
    return {"status": "ok" if ok else "not_found", "id": report_id, "new_status": new_status}


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


@router.get("/api/admin/onboarding-funnel")
async def admin_onboarding_funnel(_admin: str = Depends(require_admin)):
    """Воронка онбординга: где люди останавливаются и сколько занимает путь.

    Отвечает на три вопроса, ради которых воронку и заводили (ROADMAP §R4-R5):
    сколько установок дошло до каждой ступени, сколько времени занял путь до
    технической готовности (TTTR, §5.2) и на каких кодах ошибок отваливаются.

    ДВЕ ШКАЛЫ, и путать их нельзя. Шаги Manager считаются по анонимной
    УСТАНОВКЕ: один человек, одна машина. Всё, что после — heartbeat мода,
    первое действие зрителя, стримы — по КАНАЛУ, потому что установка к тому
    моменту уже привязана к каналу, а событий с installation_id там нет.
    Показывать их одной колонкой значило бы сравнивать разные вещи.
    """
    import onboarding

    INSTALL_STEPS = [
        ("manager_started",         "Запустил Manager"),
        # Порядок как в приложении: игра выбрана ДО поиска её папки. Раньше
        # «выбрал игру» стояло после «игра найдена», и воронка показывала
        # отрицательный отвал — люди «терялись» и появлялись снова.
        ("integration_selected",    "Выбрал игру"),
        ("game_detection_started",  "Начал поиск игры"),
        ("game_detected",           "Игра найдена"),
        ("manager_authenticated",   "Вошёл через Twitch"),
        ("install_started",         "Начал установку"),
        ("install_completed",       "Установка завершена"),
        ("configuration_completed", "Настройка записана"),
        ("test_action_completed",   "Прогнал проверку"),
        ("technical_ready",         "Технически готов"),
    ]
    CHANNEL_STEPS = [
        ("mod_heartbeat_received",  "Мод вышел на связь"),
        ("first_viewer_action",     "Первое действие зрителя"),
        ("stream_session_started",  "Стрим с ShedLink"),
    ]

    db = get_db()
    async with db._connect() as conn:
        async def distinct(event, column):
            cur = await conn.execute(
                "SELECT COUNT(DISTINCT %s) FROM onboarding_events "
                "WHERE event=? AND %s IS NOT NULL" % (column, column), (event,))
            return (await cur.fetchone())[0]

        install_rows, previous = [], None
        for event, title in INSTALL_STEPS:
            reached = await distinct(event, "installation_id")
            lost = None if previous is None else max(0, previous - reached)
            install_rows.append({
                "event": event, "title": title,
                "reached": reached, "lost_here": lost,
            })
            previous = reached

        channel_rows = []
        for event, title in CHANNEL_STEPS:
            channel_rows.append({
                "event": event, "title": title,
                "reached": await distinct(event, "channel_id"),
            })

        # TTTR: от запуска Manager до технической готовности, по установкам, у
        # которых есть обе отметки. Медиана, а не среднее: один человек,
        # ушедший пить чай на два часа, не должен красить картину.
        cur = await conn.execute(
            "SELECT r.installation_id, MIN(r.created_at) - MIN(s.created_at) "
            "FROM onboarding_events r "
            "JOIN onboarding_events s ON s.installation_id = r.installation_id "
            "                        AND s.event = 'manager_started' "
            "WHERE r.event = 'technical_ready' AND r.installation_id IS NOT NULL "
            "GROUP BY r.installation_id")
        def _median(values):
            values = sorted(values)
            if not values:
                return None
            middle = len(values) // 2
            return (values[middle] if len(values) % 2
                    else (values[middle - 1] + values[middle]) / 2)

        durations = [float(row[1]) for row in await cur.fetchall()
                     if row[1] is not None and float(row[1]) >= 0]
        tttr_median = _median(durations)

        # 2026-08-20, по первому живому прогону. TTTR по определению ROADMAP
        # §5.2 идёт до успешного тест-действия, а значит ВКЛЮЧАЕТ загрузку
        # игры и паузу, пока человек дойдёт до кнопки. У владельца из 8 мин
        # 52 с на сам Manager ушло 14 секунд, остальное — Bannerlord грузился
        # и ждал нажатия. Ворота M1 «меньше 10 минут» в таком виде меряют
        # скорее игру и терпение, чем продукт.
        #
        # Поэтому рядом считаем то, чем продукт УПРАВЛЯЕТ: от запуска Manager
        # до записанной конфигурации. Обе цифры вместе отвечают на разные
        # вопросы, и подменять одну другой нельзя.
        cur = await conn.execute(
            "SELECT c.installation_id, MIN(c.created_at) - MIN(s.created_at) "
            "FROM onboarding_events c "
            "JOIN onboarding_events s ON s.installation_id = c.installation_id "
            "                        AND s.event = 'manager_started' "
            "WHERE c.event = 'configuration_completed' "
            "  AND c.installation_id IS NOT NULL "
            "GROUP BY c.installation_id")
        manager_work = [float(row[1]) for row in await cur.fetchall()
                        if row[1] is not None and float(row[1]) >= 0]
        manager_work_median = _median(manager_work)

        # На чём спотыкаются: коды неуспешных установок.
        cur = await conn.execute(
            "SELECT result, COUNT(*) FROM onboarding_events "
            "WHERE event='install_completed' AND result IS NOT NULL AND result <> 'ok' "
            "GROUP BY result ORDER BY COUNT(*) DESC LIMIT 10")
        failures = [{"code": r[0], "count": r[1]} for r in await cur.fetchall()]

        cur = await conn.execute(
            "SELECT COUNT(*), MIN(created_at), MAX(created_at) FROM onboarding_events")
        total, first_at, last_at = await cur.fetchone()

        # Скачивания — отдельной строкой и отдельной шкалой: у них нет
        # installation_id, это «сколько раз», а не «сколько людей». Сложить их
        # с остальными ступенями значило бы получить красивое неверное число.
        cur = await conn.execute(
            "SELECT COUNT(*) FROM onboarding_events WHERE event=?",
            (onboarding.DOWNLOAD_EVENT,))
        downloads = (await cur.fetchone())[0]

    return {
        "success": True,
        "events_total": total,
        "first_event_at": first_at,
        "last_event_at": last_at,
        "install_steps": install_rows,
        "channel_steps": channel_rows,
        "tttr_median_sec": tttr_median,
        "tttr_samples": len(durations),
        "manager_work_median_sec": manager_work_median,
        "manager_work_samples": len(manager_work),
        "install_failures": failures,
        "downloads_total": downloads,
        # Разрыв между «скачали» и «запустили» — первая точка отвала, и там
        # стоит неподписанный exe с предупреждением Windows.
        "downloads_vs_starts": (
            None if not downloads
            else downloads - (install_rows[0]["reached"] if install_rows else 0)),
        "scale_note": (
            "Скачивания считаются по журналу веб-сервера: это «сколько раз», "
            "а не «сколько людей» — идентификатор установки появляется только "
            "при первом запуске."),
    }
