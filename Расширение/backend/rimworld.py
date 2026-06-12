# rimworld.py — RimWorld legacy routes (1981 line monolith).
#
# DEPRECATION NOTICE (2026-05-08):
# Этот файл — исторический monolith с 30+ /api/rimworld/* endpoint'ами.
# Migration to Module API path в process'е, см. docs/MODULE_MIGRATION.md.
#
# Что СЕЙЧАС:
#   - Endpoints вызывают C# мод напрямую (HTTP) и пишут в БД сырыми SQL
#     через aiosqlite.connect(db.db_path) (30 мест — bypass pool, не идеально).
#   - Параллельно работает Module API (см. routes/module_api.py + modules/
#     rimworld/) который ждёт когда C# мод его подключит.
#
# Что БУДЕТ (Step 6.b decommission):
#   - Когда C# мод переедет на POST /v1/module/rimworld/events + GET /actions
#     (shape per docs/MODULE_API.md):
#       * /api/rimworld/link        → event player.linked
#       * /api/rimworld/unlink      → event player.unlinked
#       * /api/rimworld/sync_pawns  → event player.state_update
#       * /api/rimworld/spawn       → action player.spawn (через queue)
#       * /api/rimworld/heal        → action player.heal
#       * /api/rimworld/equip       → action player.equip_item
#       * /api/rimworld/add_trait   → action pawn.add_trait (extension)
#       * /api/rimworld/add_gene    → action pawn.add_gene (extension)
#       * ... остальные аналогично
#   - После полного перевода → этот файл становится 50-line shim или удаляется.
#
# До тех пор:
#   - НЕ добавлять новый endpoint сюда — добавлять в Module API path
#     (events/actions через manifest)
#   - aiosqlite.connect(db.db_path) → НЕ копировать pattern, использовать
#     db._connect() (через pool) в новом коде

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from datetime import datetime
import aiosqlite
import asyncio
import json
import os
import time
import traceback

from config import sanitize_username, RIMWORLD_OFFLINE_TIMEOUT
from dependencies import require_jwt_channel, require_jwt_user

router = APIRouter()
_security = HTTPBasic()

# ── Security 2.1 (2026-06-12): RimWorld mod-ingest auth ──────────────────────
# 13 mod-side endpoints accepted UNAUTHENTICATED writes (wipe pawns / rig shop
# catalog / inject pawns). Gate them with the module-token — mirrors Bannerlord
# (issue_module_token / verify_module_token in routes/streamer.py).
# Rollout-safe: SOFT mode (default) logs a missing/invalid token but ALLOWS the
# request, so nothing breaks while the RimLink mod is updated to send it. Set
# env RIMWORLD_REQUIRE_TOKEN=1 to enforce (401) once the mod is confirmed sending it.
_RIMWORLD_REQUIRE_TOKEN = os.getenv("RIMWORLD_REQUIRE_TOKEN", "").lower() in ("1", "true", "yes")
_rimworld_soft_warned = False

async def rimworld_mod_auth(request: Request):
    """Verify the RimWorld module-token on a mod-ingest request. Returns the
    token's channel_id when valid; in SOFT mode returns None (allowed) for a
    missing/invalid token, in STRICT mode raises 401."""
    from routes.streamer import verify_module_token  # lazy import: avoid cycle
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
    claims = verify_module_token(token) if token else None
    if claims and claims.get("module_id") == "rimworld":
        return claims.get("channel_id")
    if _RIMWORLD_REQUIRE_TOKEN:
        raise HTTPException(status_code=401, detail="rimworld module token required")
    global _rimworld_soft_warned
    if not _rimworld_soft_warned:
        print("⚠️ [rimworld-auth] SOFT mode — mod request without valid module-token "
              "(allowed for now; set RIMWORLD_REQUIRE_TOKEN=1 to enforce after mod update)")
        _rimworld_soft_warned = True
    return None

# Маппинг категории → тип команды
CATEGORY_TO_CMD = {
    "apparel":      "equip_item",
    "weapon":       "equip_item",
    "implant":      "install_implant",
    "neurotrainer": "train_skill",
    "gene":         "add_gene",
    "xenotype":     "add_xenotype",
    "trait":        "add_trait",
}

# Таблицы для очистки данных пешки
PAWN_DATA_TABLES = [
    "rimworld_pawn_equipment", "rimworld_pawn_skills",
    "rimworld_pawn_hediffs", "rimworld_pawn_traits", "rimworld_pawn_genes"
]

# In-memory кэш тултипов — def_name → tooltip строка.
# Заполняется при получении каталога от мода, в БД не хранится.
# Персистится в JSON файл чтобы переживать рестарт сервера.
_tooltip_cache: dict = {}
_TOOLTIP_CACHE_FILE = "tooltip_cache.json"

HEAL_COOLDOWN_SECONDS = 15 * 60  # 15 минут

def _load_tooltip_cache():
    """Загружает кэш тултипов с диска при старте."""
    global _tooltip_cache
    if os.path.exists(_TOOLTIP_CACHE_FILE):
        try:
            with open(_TOOLTIP_CACHE_FILE, "r", encoding="utf-8") as f:
                _tooltip_cache = json.load(f)
            print(f"🗂️ Тултипы загружены: {len(_tooltip_cache)} предметов")
        except Exception as e:
            print(f"⚠️ Не удалось загрузить tooltip_cache.json: {e}")

def _save_tooltip_cache():
    """Сохраняет кэш тултипов на диск."""
    try:
        with open(_TOOLTIP_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_tooltip_cache, f, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Не удалось сохранить tooltip_cache.json: {e}")

# Загружаем при импорте модуля
_load_tooltip_cache()

# Импортируем из main контекст (db, bot, pending_commands, require_admin)
# Используем late-binding чтобы избежать циклических импортов
def get_db():
    import main as _main
    return _main.db

def get_bot():
    import main as _main
    return _main.bot

def require_admin(credentials: HTTPBasicCredentials = Depends(_security)):
    """Proxy для main.require_admin — делегирует проверку в main."""
    import main as _main
    return _main.require_admin(credentials)

def get_pending():
    import main as _main
    return _main.pending_commands

_commands_lock = asyncio.Lock()

def get_commands_lock():
    return _commands_lock

async def _require_stream_live(channel_id=None):
    """Проверка стрима для rimworld эндпоинтов — через bot из main.

    Bug 4 fix (2026-05-10): channel_id опциональный. RimWorld-эндпоинты
    дёргаются с C# мода через TWITCH_BROADCASTER_ID и из админки —
    fallback на ContextVar/legacy резолвится внутри _is_stream_live.

    Возвращает dict с ошибкой если стрим недоступен или проверка упала,
    None — если стрим живой.

    Testing bypass (2026-05-14): TESTING_BYPASS_STREAM_LIVE=true в .env
    отключает проверку — для функционального теста без стрима."""
    from config import TESTING_BYPASS_STREAM_LIVE
    if TESTING_BYPASS_STREAM_LIVE:
        return None
    try:
        import main as _main
        live = await _main.bot._is_stream_live(channel_id=channel_id)
        if not live:
            return {"success": False, "message": "⚡ Доступно только во время стрима"}
    except Exception as e:
        print(f"⚠️ _require_stream_live: ошибка проверки стрима: {e}")
        return {"success": False, "message": "⚡ Не удалось проверить статус стрима"}
    return None

async def _ensure_pending_commands_table(conn):
    """Создаёт таблицу отложенных команд если её нет."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS rimworld_pending_commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cmd_id TEXT UNIQUE,
            cmd_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

async def _db_enqueue_command(cmd: dict):
    """Сохранить команду в БД (переживёт рестарт сервера)"""
    db = get_db()
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            await _ensure_pending_commands_table(conn)
            await conn.execute(
                "INSERT OR IGNORE INTO rimworld_pending_commands (cmd_id, cmd_json) VALUES (?, ?)",
                (cmd.get('id', ''), json.dumps(cmd, ensure_ascii=False))
            )
            await conn.commit()
    except Exception as e:
        print(f"⚠️ db_enqueue: {e}")

async def _ensure_heal_cooldowns_table(conn):
    """Создаёт таблицу кулдаунов лечения если её нет."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS rimworld_heal_cooldowns (
            username TEXT PRIMARY KEY,
            last_heal_ts REAL NOT NULL
        )
    """)

async def _get_last_heal_ts(username: str) -> float:
    """Получить timestamp последнего лечения (0 если нет данных)."""
    db = get_db()
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            await _ensure_heal_cooldowns_table(conn)
            cur = await conn.execute(
                "SELECT last_heal_ts FROM rimworld_heal_cooldowns WHERE username = ?",
                (username.lower(),)
            )
            row = await cur.fetchone()
            return float(row[0]) if row else 0.0
    except Exception as e:
        print(f"⚠️ get_heal_ts: {e}")
        return 0.0

async def _set_last_heal_ts(username: str, ts: float):
    """Сохранить timestamp последнего лечения."""
    db = get_db()
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            await _ensure_heal_cooldowns_table(conn)
            await conn.execute("""
                INSERT INTO rimworld_heal_cooldowns (username, last_heal_ts)
                VALUES (?, ?)
                ON CONFLICT(username) DO UPDATE SET last_heal_ts = excluded.last_heal_ts
            """, (username.lower(), float(ts)))
            await conn.commit()
    except Exception as e:
        print(f"⚠️ set_heal_ts: {e}")

async def _db_dequeue_commands():
    """Достать и удалить все команды из БД (восстановление после рестарта)"""
    db = get_db()
    result = []
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            await _ensure_pending_commands_table(conn)
            cursor = await conn.execute(
                "SELECT cmd_json FROM rimworld_pending_commands ORDER BY id LIMIT 50")
            rows = await cursor.fetchall()
            if rows:
                for row in rows:
                    try:
                        result.append(json.loads(row[0]))
                    except Exception:
                        pass
                await conn.execute("DELETE FROM rimworld_pending_commands")
                await conn.commit()
                print(f"♻️ Восстановлено {len(result)} команд из БД после рестарта")
    except Exception as e:
        print(f"⚠️ db_dequeue: {e}")
    return result

# ===== ГЛОБАЛЬНЫЕ =====
rimworld_last_heartbeat: datetime = None
# RIMWORLD_OFFLINE_TIMEOUT импортируется из config.py


# ===== СТАТУС =====

@router.get("/api/rimworld/status")
async def rimworld_status():
    """Статус подключения RimWorld"""
    global rimworld_last_heartbeat
    if rimworld_last_heartbeat is None:
        return {"online": False}
    elapsed = (datetime.utcnow() - rimworld_last_heartbeat).total_seconds()
    return {"online": elapsed < RIMWORLD_OFFLINE_TIMEOUT, "last_seen": int(elapsed)}

@router.post("/api/rimworld/heartbeat")
async def rimworld_heartbeat(_auth=Depends(rimworld_mod_auth)):
    global rimworld_last_heartbeat
    rimworld_last_heartbeat = datetime.utcnow()
    return {"status": "ok"}

@router.post("/api/rimworld/offline")
async def rimworld_offline(_auth=Depends(rimworld_mod_auth)):
    global rimworld_last_heartbeat
    rimworld_last_heartbeat = None
    return {"status": "ok"}


# ===== СЕССИЯ =====

@router.post("/api/rimworld/session-start")
async def rimworld_session_start(_auth=Depends(rimworld_mod_auth)):
    """Вызывается при загрузке игры — очищает старых пешек"""
    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute("SELECT COUNT(*) FROM rimworld_pawns")
        count = (await cursor.fetchone())[0]
        cursor2 = await conn.execute("SELECT id FROM rimworld_pawns")
        rows = await cursor2.fetchall()
        for row in rows:
            pid = row[0]
            for tbl in ["rimworld_pawn_equipment", "rimworld_pawn_skills",
                        "rimworld_pawn_hediffs", "rimworld_pawn_traits", "rimworld_pawn_genes"]:
                await conn.execute(f"DELETE FROM {tbl} WHERE pawn_id = ?", (pid,))
        await conn.execute("DELETE FROM rimworld_pawns")
        await conn.commit()
    print(f"🔄 Session start: очищено {count} пешек")
    return {"status": "ok", "cleared": count}


# ===== СИНХРОНИЗАЦИЯ ПЕШКИ =====

@router.post("/api/rimworld/sync-pawn")
async def sync_pawn(request: Request, _auth=Depends(rimworld_mod_auth)):
    """Синхронизация одной пешки с детальными данными"""
    db = get_db()
    try:
        data = await request.json()
        username  = data.get('username')
        pawn_name = data.get('pawn_name')
        is_alive  = data.get('is_alive', True)
        health    = data.get('health', 1.0)
        world_id  = data.get('world_id') or data.get('map_id') or ''
        world_name = data.get('world_name', '')

        if not username:
            return {"status": "error", "message": "no username"}

        # Только уведомление о смерти/удалении — нет имени пешки
        if not pawn_name:
            async with aiosqlite.connect(db.db_path) as conn:
                cursor = await conn.execute(
                    "SELECT id FROM rimworld_pawns WHERE username = ?", (username,))
                row = await cursor.fetchone()
                if row:
                    # Помечаем мёртвой, НЕ удаляем — расширение должно показать кнопку воскрешения
                    await conn.execute(
                        "UPDATE rimworld_pawns SET is_alive=0 WHERE username=?", (username,))
                    await conn.commit()
            return {"status": "ok", "action": "marked_dead"}

        print(f"📥 Синхронизация пешки {username} ({pawn_name}), alive={is_alive}")

        async with aiosqlite.connect(db.db_path) as conn:
            # Создаём таблицы если нет
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_pawns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE,
                    pawn_name TEXT,
                    is_alive INTEGER DEFAULT 1,
                    health REAL DEFAULT 1.0,
                    world_id TEXT,
                    world_name TEXT,
                    last_sync TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_pawn_traits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pawn_id INTEGER,
                    trait_def TEXT,
                    degree INTEGER DEFAULT 0,
                    label TEXT,
                    trait_desc TEXT
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_pawn_equipment (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pawn_id INTEGER,
                    slot TEXT,
                    item_def TEXT,
                    item_name TEXT,
                    hp REAL DEFAULT 100,
                    meta TEXT
                )
            """)
            # Миграция: добавить колонку meta в старую схему, если её нет.
            try:
                await conn.execute("ALTER TABLE rimworld_pawn_equipment ADD COLUMN meta TEXT")
            except Exception:
                pass  # колонка уже есть — OK
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_pawn_hediffs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pawn_id INTEGER,
                    body_part TEXT,
                    hediff_label TEXT,
                    severity REAL DEFAULT 0,
                    age_ticks INTEGER DEFAULT 0
                )
            """)

            # Ищем существующую пешку
            cursor = await conn.execute(
                "SELECT id FROM rimworld_pawns WHERE username = ?", (username,))
            old_row = await cursor.fetchone()

            if old_row:
                pawn_id = old_row[0]
                # Обновляем основные данные
                await conn.execute("""
                    UPDATE rimworld_pawns
                    SET pawn_name=?, is_alive=?, health=?, world_id=?, world_name=?, last_sync=CURRENT_TIMESTAMP
                    WHERE id=?
                """, (pawn_name, 1 if is_alive else 0, health, world_id, world_name, pawn_id))
            else:
                # Новая пешка
                await conn.execute("""
                    INSERT INTO rimworld_pawns (username, pawn_name, is_alive, health, world_id, world_name)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (username, pawn_name, 1 if is_alive else 0, health, world_id, world_name))
                cursor = await conn.execute(
                    "SELECT id FROM rimworld_pawns WHERE username = ?", (username,))
                row = await cursor.fetchone()
                if not row:
                    return {"status": "error", "message": "Failed to get pawn ID"}
                pawn_id = row[0]

            # Очищаем старые данные
            for tbl in PAWN_DATA_TABLES:
                await conn.execute(f"DELETE FROM {tbl} WHERE pawn_id = ?", (pawn_id,))

            # --- Экипировка ---
            for eq in data.get('equipment', []):
                meta = {k: eq.get(k) for k in (
                    'max_hp', 'quality', 'stuff', 'description', 'color',
                    'weapon_traits', 'psi_abilities', 'is_bladelink'
                ) if eq.get(k) not in (None, '', [], {})}
                await conn.execute("""
                    INSERT INTO rimworld_pawn_equipment (pawn_id, slot, item_def, item_name, hp, meta)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    pawn_id,
                    eq.get('slot', 'body'),
                    eq.get('def_name', eq.get('item_def', '')),
                    eq.get('label', eq.get('item_name', '')),
                    eq.get('hp', 100),
                    json.dumps(meta, ensure_ascii=False) if meta else None
                ))

            # --- Навыки (с is_disabled) ---
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_pawn_skills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pawn_id INTEGER,
                    skill_name TEXT,
                    skill_level INTEGER DEFAULT 0,
                    passion INTEGER DEFAULT 0,
                    xp INTEGER DEFAULT 0,
                    is_disabled INTEGER DEFAULT 0
                )
            """)
            for skill in data.get('skills', []):
                await conn.execute("""
                    INSERT INTO rimworld_pawn_skills
                    (pawn_id, skill_name, skill_level, passion, xp, is_disabled)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    pawn_id,
                    skill.get('def_name', skill.get('name', skill.get('label', ''))),
                    skill.get('level', 0),
                    skill.get('passion', 0),
                    skill.get('xp', 0),
                    1 if skill.get('is_disabled', skill.get('disabled', False)) else 0
                ))

            # --- Черты характера (всегда, не только для новых) ---
            for t in data.get('traits', []):
                tdef = t.get('def_name', '')
                if not tdef:
                    continue
                await conn.execute("""
                    INSERT INTO rimworld_pawn_traits (pawn_id, trait_def, degree, label, trait_desc)
                    VALUES (?, ?, ?, ?, ?)
                """, (pawn_id, tdef, t.get('degree', 0), t.get('label', ''), t.get('desc', '')))

            # --- Хедиффы (раны, болезни) ---
            for h in data.get('hediffs', []):
                label = str(h.get('label', h.get('hediff_label', ''))).strip()
                if not label:
                    continue
                await conn.execute("""
                    INSERT INTO rimworld_pawn_hediffs (pawn_id, body_part, hediff_label, severity, age_ticks)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    pawn_id,
                    h.get('part', h.get('body_part', 'тело')),
                    label,
                    h.get('severity', 0.0),
                    h.get('age_ticks', 0)
                ))

            # --- Импланты (мод шлёт отдельным ключом 'implants') ---
            for h in data.get('implants', []):
                label = str(h.get('label', '')).strip()
                if not label:
                    continue
                await conn.execute("""
                    INSERT INTO rimworld_pawn_hediffs
                        (pawn_id, body_part, hediff_label, severity, age_ticks,
                         hediff_def, part_def, is_paired, is_left)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    pawn_id,
                    h.get('part_label', h.get('part', 'тело')),
                    label,
                    0.0,
                    0,
                    h.get('def_name', ''),
                    h.get('part_def', ''),
                    1 if h.get('is_paired') else 0,
                    # is_left: True→1, False→0, ''→None
                    (1 if h.get('is_left') is True else (0 if h.get('is_left') is False else None)),
                ))

            # --- Гены (Biotech) ---
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_pawn_genes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pawn_id INTEGER NOT NULL,
                    def_name TEXT NOT NULL,
                    label TEXT,
                    is_active INTEGER DEFAULT 1,
                    xenogene INTEGER DEFAULT 1,
                    gene_class TEXT DEFAULT '',
                    FOREIGN KEY (pawn_id) REFERENCES rimworld_pawns(id)
                )
            """)
            # (rimworld_pawn_genes уже очищена в цикле for tbl выше)
            for g in data.get('genes', []):
                def_n = g.get('def_name', '')
                if not def_n:
                    continue
                await conn.execute("""
                    INSERT INTO rimworld_pawn_genes (pawn_id, def_name, label, is_active, xenogene, gene_class)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    pawn_id,
                    def_n,
                    g.get('label', def_n),
                    1 if g.get('is_active', True) else 0,
                    1 if g.get('xenogene', True) else 0,
                    g.get('gene_class', '')
                ))

            await conn.commit()

        return {"status": "ok"}

    except Exception as e:
        print(f"❌ Ошибка синхронизации пешки: {e}")
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


# ===== ДАННЫЕ ПЕШКИ ДЛЯ РАСШИРЕНИЯ =====

@router.get("/api/rimworld/my-pawn/{username}")
async def get_my_pawn(username: str):
    """Получить полную информацию о пешке зрителя"""
    db = get_db()
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            cursor = await conn.execute("""
                SELECT id, pawn_name, is_alive, health, world_id, world_name
                FROM rimworld_pawns WHERE username = ?
            """, (username,))
            pawn = await cursor.fetchone()

            if not pawn:
                return {"exists": False}

            pawn_id = pawn[0]

            # Экипировка (+ meta JSON с weapon_traits/psi/quality/и т.д.)
            cursor = await conn.execute("""
                SELECT slot, item_def, item_name, hp, meta
                FROM rimworld_pawn_equipment WHERE pawn_id = ?
            """, (pawn_id,))
            equipment = await cursor.fetchall()

            # Навыки с is_disabled
            cursor = await conn.execute("""
                SELECT skill_name,
                       CASE WHEN COALESCE(is_disabled, 0) = 1 THEN 0 ELSE MAX(skill_level, 0) END,
                       passion, xp,
                       COALESCE(is_disabled, 0)
                FROM rimworld_pawn_skills WHERE pawn_id = ?
                ORDER BY skill_level DESC
            """, (pawn_id,))
            skills = await cursor.fetchall()

            # Черты
            traits = []
            try:
                cursor = await conn.execute("""
                    SELECT trait_def, degree, label, trait_desc
                    FROM rimworld_pawn_traits WHERE pawn_id = ?
                """, (pawn_id,))
                traits = await cursor.fetchall()
            except Exception:
                pass

            # Хедиффы
            cursor = await conn.execute("""
                SELECT body_part, hediff_label, severity, age_ticks,
                       hediff_def, part_def, is_paired, is_left
                FROM rimworld_pawn_hediffs WHERE pawn_id = ?
            """, (pawn_id,))
            hediffs = await cursor.fetchall()

            # Гены
            genes = []
            try:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS rimworld_pawn_genes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        pawn_id INTEGER NOT NULL,
                        def_name TEXT NOT NULL,
                        label TEXT,
                        is_active INTEGER DEFAULT 1,
                        xenogene INTEGER DEFAULT 1,
                        gene_class TEXT DEFAULT '',
                        FOREIGN KEY (pawn_id) REFERENCES rimworld_pawns(id)
                    )
                """)
                cursor = await conn.execute("""
                    SELECT def_name, label, is_active, xenogene, gene_class
                    FROM rimworld_pawn_genes WHERE pawn_id = ?
                    ORDER BY xenogene DESC, label
                """, (pawn_id,))
                genes = await cursor.fetchall()
            except Exception:
                pass

            return {
                "exists": True,
                "pawn_name": pawn[1],
                "is_alive": bool(pawn[2]),
                "health": pawn[3],
                "world_id": pawn[4],
                "world_name": pawn[5],
                "equipment": [
                    {
                        "slot": e[0], "item_def": e[1], "label": e[2], "name": e[2], "hp": e[3],
                        "tooltip": _tooltip_cache.get(e[1], ""),
                        # Разворачиваем meta обратно в поля для фронта (weapon_traits, psi_abilities,
                        # is_bladelink, quality, stuff, max_hp, description, color).
                        **(json.loads(e[4]) if e[4] else {})
                    }
                    for e in equipment
                ],
                "skills": [
                    {"def_name": s[0], "name": s[0], "level": s[1], "passion": s[2], "xp": s[3], "disabled": bool(s[4]), "is_disabled": bool(s[4])}
                    for s in skills
                ],
                "traits": [
                    {"def_name": t[0], "degree": t[1], "label": t[2], "desc": t[3]}
                    for t in traits
                ],
                "hediffs": [
                    {
                        "part":      h[0],
                        "label":     h[1],
                        "severity":  h[2],
                        "age_ticks": h[3],
                        "def_name":  h[4] if len(h) > 4 else "",
                        "part_def":  h[5] if len(h) > 5 else "",
                        "is_paired": bool(h[6]) if len(h) > 6 and h[6] is not None else False,
                        "is_left":   (True if h[7] == 1 else (False if h[7] == 0 else None)) if len(h) > 7 else None,
                    }
                    for h in hediffs
                ],
                "genes": [
                    {"def_name": g[0], "label": g[1], "is_active": bool(g[2]),
                     "xenogene": bool(g[3]), "gene_class": g[4]}
                    for g in genes
                ]
            }

    except Exception as e:
        print(f"❌ Ошибка получения пешки: {e}")
        return {"exists": False, "error": str(e)}


# ===== МАССОВАЯ СИНХРОНИЗАЦИЯ ПЕШЕК =====

@router.post("/api/rimworld/sync-pawns")
async def sync_pawns_bulk(request: Request, _auth=Depends(rimworld_mod_auth)):
    """Массовая синхронизация пешек (правильная версия)"""
    db = get_db()
    from dependencies import resolve_channel_id_or_default  # mod endpoint без JWT — TODO M4.5+: HMAC + явный channel_id из мода
    channel_id = resolve_channel_id_or_default()
    try:
        pawns_data = await request.json()
        if not isinstance(pawns_data, list):
            return {"status": "error", "message": "Expected list of pawns"}

        print(f"📥 Массовая синхронизация: {len(pawns_data)} пешек")

        async with aiosqlite.connect(db.db_path) as conn:
            for pawn_data in pawns_data:
                username = pawn_data.get('username')
                if not username:
                    continue

                pawn_name = pawn_data.get('pawn_name', '')
                is_alive = pawn_data.get('is_alive', True)
                health = pawn_data.get('health', 1.0)
                world_id = pawn_data.get('world_id', pawn_data.get('map_id', ''))
                world_name = pawn_data.get('world_name', '')

                # Обновляем или вставляем пешку
                await conn.execute("""
                    INSERT INTO rimworld_pawns (channel_id, username, pawn_name, is_alive, health, world_id, world_name, last_sync)
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(channel_id, username) DO UPDATE SET
                        pawn_name = excluded.pawn_name,
                        is_alive = excluded.is_alive,
                        health = excluded.health,
                        world_id = excluded.world_id,
                        world_name = excluded.world_name,
                        last_sync = CURRENT_TIMESTAMP
                """, (channel_id, username, pawn_name, 1 if is_alive else 0, health, world_id, world_name))

                # Получаем pawn_id
                cursor = await conn.execute("SELECT id FROM rimworld_pawns WHERE channel_id = ? AND username = ?", (channel_id, username))
                row = await cursor.fetchone()
                if not row:
                    continue
                pawn_id = row[0]
                
                # Очищаем старые данные
                for tbl in PAWN_DATA_TABLES:
                    await conn.execute(f"DELETE FROM {tbl} WHERE pawn_id = ?", (pawn_id,))
                
                # Сохраняем экипировку (с meta-JSON для weapon_traits/psi/quality/...)
                for eq in pawn_data.get('equipment', []):
                    meta = {k: eq.get(k) for k in (
                        'max_hp', 'quality', 'stuff', 'description', 'color',
                        'weapon_traits', 'psi_abilities', 'is_bladelink'
                    ) if eq.get(k) not in (None, '', [], {})}
                    await conn.execute("""
                        INSERT INTO rimworld_pawn_equipment (pawn_id, slot, item_def, item_name, hp, meta)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        pawn_id,
                        eq.get('slot', 'body'),
                        eq.get('def_name', eq.get('item_def', '')),
                        eq.get('label', eq.get('item_name', '')),
                        eq.get('hp', 100),
                        json.dumps(meta, ensure_ascii=False) if meta else None
                    ))
                
                # Сохраняем навыки
                for skill in pawn_data.get('skills', []):
                    await conn.execute("""
                        INSERT INTO rimworld_pawn_skills
                        (pawn_id, skill_name, skill_level, passion, xp, is_disabled)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        pawn_id,
                        skill.get('def_name', skill.get('name', skill.get('label', ''))),
                        skill.get('level', 0),
                        skill.get('passion', 0),
                        skill.get('xp', 0),
                        1 if skill.get('is_disabled', skill.get('disabled', False)) else 0
                    ))
                
                # Сохраняем черты
                for trait in pawn_data.get('traits', []):
                    await conn.execute("""
                        INSERT INTO rimworld_pawn_traits (pawn_id, trait_def, degree, label, trait_desc)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        pawn_id,
                        trait.get('def_name', ''),
                        trait.get('degree', 0),
                        trait.get('label', ''),
                        trait.get('desc', '')
                    ))
                
                # Сохраняем хедиффы
                for hediff in pawn_data.get('hediffs', []):
                    await conn.execute("""
                        INSERT INTO rimworld_pawn_hediffs (pawn_id, body_part, hediff_label, severity, age_ticks)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        pawn_id,
                        hediff.get('part', hediff.get('body_part', 'тело')),
                        hediff.get('label', hediff.get('hediff_label', '')),
                        hediff.get('severity', 0.0),
                        hediff.get('age_ticks', 0)
                    ))

                # Сохраняем импланты (отдельный ключ от мода)
                for h in pawn_data.get('implants', []):
                    label = str(h.get('label', '')).strip()
                    if not label:
                        continue
                    await conn.execute("""
                        INSERT INTO rimworld_pawn_hediffs
                            (pawn_id, body_part, hediff_label, severity, age_ticks,
                             hediff_def, part_def, is_paired, is_left)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        pawn_id,
                        h.get('part_label', h.get('part_label_full', 'тело')),
                        label,
                        0.0,
                        0,
                        h.get('def_name', ''),
                        h.get('part_def', ''),
                        1 if h.get('is_paired') else 0,
                        (1 if h.get('is_left') is True else (0 if h.get('is_left') is False else None)),
                    ))

                # Сохраняем гены (Biotech)
                for g in pawn_data.get('genes', []):
                    def_n = g.get('def_name', '')
                    if not def_n:
                        continue
                    await conn.execute("""
                        INSERT INTO rimworld_pawn_genes (pawn_id, def_name, label, is_active, xenogene, gene_class)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        pawn_id,
                        def_n,
                        g.get('label', def_n),
                        1 if g.get('is_active', True) else 0,
                        1 if g.get('xenogene', False) else 0,
                        g.get('gene_class', ''),
                    ))

            await conn.commit()
            
        return {"status": "ok", "count": len(pawns_data)}
    except Exception as e:
        print(f"❌ Ошибка массовой синхронизации: {e}")
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


# ===== КОМАНДЫ =====

@router.get("/api/rimworld/commands")
async def get_commands(_auth=Depends(rimworld_mod_auth)):
    """Мод забирает команды для выполнения"""
    async with get_commands_lock():
        return await _get_commands_inner()

async def _get_commands_inner():
    pending = get_pending()
    if not pending:
        recovered = await _db_dequeue_commands()
        pending.extend(recovered)
    all_cmds = list(pending)
    pending.clear()
    invalid = [c for c in all_cmds if not c.get('type')]
    if invalid:
        print(f"⚠️ Отфильтровано {len(invalid)} команд без поля 'type' (игнорируются)")
    cmds = [c for c in all_cmds if c.get('type')]
    if cmds:
        db = get_db()
        try:
            cmd_ids = [cmd.get('id', '') for cmd in cmds if cmd.get('id')]
            if cmd_ids:
                async with aiosqlite.connect(db.db_path) as conn:
                    placeholders = ','.join('?' * len(cmd_ids))
                    await conn.execute(
                        f"DELETE FROM rimworld_pending_commands WHERE cmd_id IN ({placeholders})",
                        cmd_ids
                    )
                    await conn.commit()
        except Exception as e:
            print(f"⚠️ Очистка команд из БД: {e}")
    return cmds


@router.post("/api/rimworld/ack-command")
async def ack_command(request: Request, _auth=Depends(rimworld_mod_auth)):
    data = await request.json()
    print(f"✅ Команда {data.get('command_id')} выполнена: success={data.get('success')}")
    return {"status": "ok"}

@router.post("/api/rimworld/commands-processed")
async def commands_processed(request: Request, _auth=Depends(rimworld_mod_auth)):
    """Мод уведомляет о завершении обработки пакета команд"""
    data = await request.json()
    count = data.get('processed', 0)
    print(f"✅ Обработано команд: {count}")
    return {"status": "ok"}

@router.post("/api/rimworld/add-command")
async def add_command(request: Request):
    data = await request.json()
    if not data.get("type"):
        print(f"⚠️ add-command: отклонена команда без поля 'type': {data}")
        return {"status": "error", "message": "Missing 'type' field"}
    async with get_commands_lock():
        get_pending().append(data)
        await _db_enqueue_command(data)
    return {"status": "ok"}


# ===== МАГАЗИН / КАТАЛОГ =====

@router.post("/api/rimworld/shop-catalog")
async def receive_shop_catalog(request: Request, _auth=Depends(rimworld_mod_auth)):
    """Принимает каталог предметов от мода"""
    db = get_db()
    try:
        items = await request.json()
        if not isinstance(items, list):
            return {"status": "error", "message": "Expected list"}

        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS shop_catalog (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT,
                    def_name TEXT UNIQUE,
                    label TEXT,
                    description TEXT,
                    price INTEGER,
                    base_price INTEGER DEFAULT 0,
                    tech_level TEXT,
                    extra_json TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Добавляем колонку base_price если её нет (миграция старых БД)
            try:
                await conn.execute("ALTER TABLE shop_catalog ADD COLUMN base_price INTEGER DEFAULT 0")
                await conn.commit()
            except Exception:
                pass  # колонка уже существует
            await conn.execute("DELETE FROM shop_catalog")
            for item in items:
                # tooltip — не храним в БД, кэшируем в памяти
                def_name_key = item.get('def_name', '')
                tooltip_val  = item.get('tooltip', '')
                if tooltip_val and def_name_key:
                    _tooltip_cache[def_name_key] = tooltip_val

                extra = {k: v for k, v in item.items()
                         if k not in ('category','def_name','label','desc','price',
                                      'tech_level','base_price','display_label','tooltip')}
                # base_price — для черт и генов: базовая единица прогрессивной цены
                base_price = item.get('base_price', 0)
                await conn.execute("""
                    INSERT OR REPLACE INTO shop_catalog
                    (category, def_name, label, description, price, base_price, tech_level, extra_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item.get('category', 'misc'),
                    item.get('def_name', ''),
                    item.get('display_label') or item.get('label', ''),
                    item.get('desc', ''),
                    item.get('price', 100),
                    base_price,
                    item.get('tech_level', ''),
                    json.dumps(extra, ensure_ascii=False)
                ))
            await conn.commit()

        _save_tooltip_cache()
        print(f"🛒 Каталог обновлён: {len(items)} предметов, тултипов: {len(_tooltip_cache)}")
        return {"status": "ok", "count": len(items)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/api/rimworld/catalog")
async def get_catalog(category: str = None, search: str = None, username: str = None):
    """
    Каталог предметов. Если передан username — для черт и генов price заменяется
    на актуальную прогрессивную цену (base_price * (count+1)).
    """
    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        query = "SELECT category, def_name, label, description, price, tech_level, extra_json, base_price FROM shop_catalog WHERE 1=1"
        params = []
        if category and category != 'all':
            query += " AND category = ?"
            params.append(category)
        if search:
            query += " AND (label LIKE ? OR def_name LIKE ?)"
            params += [f"%{search}%", f"%{search}%"]
        query += " ORDER BY category, price"
        try:
            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
        except Exception:
            return {"items": [], "total": 0}

    # Получаем счётчики покупок для данного зрителя (если username задан)
    trait_count = 0
    gene_count  = 0
    if username:
        trait_count = await db.get_purchase_count(username, "trait")
        gene_count  = await db.get_purchase_count(username, "gene")

    items = []
    for r in rows:
        extra = {}
        try:
            extra = json.loads(r[6]) if r[6] else {}
        except Exception:
            pass
        cat        = r[0]
        base_price = r[7] if r[7] else 0

        # Прогрессивная цена для черт и генов
        if base_price > 0 and cat in ("trait", "gene"):
            count = trait_count if cat == "trait" else gene_count
            actual_price = db.calc_progressive_price(base_price, count)
        else:
            actual_price = r[4]

        item = {
            "category":    cat,
            "def_name":    r[1],
            "label":       r[2],
            "description": r[3],
            "price":       actual_price,
            "base_price":  base_price,
            "tech_level":  r[5],
        }
        # Для черт/генов добавляем информацию о прогрессии
        if base_price > 0 and cat in ("trait", "gene"):
            count = trait_count if cat == "trait" else gene_count
            item["purchase_count"] = count
            item["next_price"]     = db.calc_progressive_price(base_price, count + 1)
        item.update(extra)
        # Подмешиваем тултип из in-memory кэша (не из БД)
        tt = _tooltip_cache.get(r[1], '')
        if tt:
            item['tooltip'] = tt
        items.append(item)

    return {"items": items, "total": len(items)}


# ===== ПОКУПКА ПРЕДМЕТА =====

@router.post("/api/rimworld/buy-item")
async def buy_item(request: Request):
    if err := await _require_stream_live():
        return err
    db = get_db()

    # JWT-защита: имя зрителя берём ИЗ ПОДПИСАННОГО JWT, не из body
    # (body-username позволял действовать от чужого имени). channel_id
    # тоже из JWT — для multi-tenant скоупинга (M3).
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    username, channel_id = auth

    data = await request.json()
    def_name = data.get('item_def') or data.get('def_name')
    if not username or not def_name:
        return {"success": False, "message": "Неверные параметры"}

    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute(
            "SELECT price, label, category FROM shop_catalog WHERE def_name = ?", (def_name,))
        item = await cursor.fetchone()

    if not item:
        return {"success": False, "message": "Предмет не найден в каталоге"}

    price, label, category = item
    balance = await db.get_points(username)
    if balance < price:
        return {"success": False, "message": f"Недостаточно очков! Нужно {price}💎, у тебя {balance}💎"}

    if not await db.remove_points(username, price):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}

    cmd_type = CATEGORY_TO_CMD.get(category)
    if not cmd_type:
        # Не даём создать бессмысленную команду — возвращаем очки
        await db.add_points(username, price)
        return {"success": False, "message": f"Категория '{category}' не поддерживает покупку через этот эндпоинт"}

    cmd = {
        "type": cmd_type,
        "id": f"buy_{username}_{int(time.time())}",
        "username": username,
        "def_name": def_name,
    }
    async with get_commands_lock():
        get_pending().append(cmd)
    await _db_enqueue_command(cmd)

    # Достижение за первую покупку в RimWorld
    try:
        from main import bot as _bot
        asyncio.create_task(_bot.check_and_unlock_achievements(username, 'rimworld_buy'))
    except Exception:
        pass
    return {"success": True, "message": f"✅ {label} куплен за {price}💎!"}


# ===== СОЗДАНИЕ / ЛЕЧЕНИЕ / ВОСКРЕШЕНИЕ =====

@router.post("/api/rimworld/create-pawn")
async def create_pawn(request: Request):
    if err := await _require_stream_live():
        return err
    db = get_db()
    # JWT-защита: имя зрителя из подписанного JWT, не из body.
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    username, channel_id = auth

    SPAWN_COST = 200
    balance = await db.get_points(username)
    if balance < SPAWN_COST:
        return {"success": False, "message": f"Нужно {SPAWN_COST}💎, у тебя {balance}💎"}

    if not await db.remove_points(username, SPAWN_COST):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}
    cmd = {
        "type": "spawn_pawn",
        "id": f"spawn_{username}_{int(time.time())}",
        "username": username
    }
    async with get_commands_lock():
        get_pending().append(cmd)
    await _db_enqueue_command(cmd)
    return {"success": True, "message": f"✨ Пешка создаётся! -{SPAWN_COST}💎"}

@router.post("/api/rimworld/heal-pawn")
async def heal_pawn(request: Request):
    if err := await _require_stream_live():
        return err
    db = get_db()
    # JWT-защита: имя зрителя из подписанного JWT, не из body.
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    username, channel_id = auth

    # Проверяем КД
    now = time.time()
    last_heal = await _get_last_heal_ts(username)
    elapsed = now - last_heal
    if elapsed < HEAL_COOLDOWN_SECONDS:
        left = int(HEAL_COOLDOWN_SECONDS - elapsed)
        mins, secs = divmod(left, 60)
        return {"success": False, "cooldown_left": left,
                "message": f"⏳ Лечение будет доступно через {mins}:{secs:02d}"}

    HEAL_COST = 150
    balance = await db.get_points(username)
    if balance < HEAL_COST:
        return {"success": False, "message": f"Нужно {HEAL_COST}💎, у тебя {balance}💎"}

    if not await db.remove_points(username, HEAL_COST):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}
    await _set_last_heal_ts(username, now)
    cmd = {
        "type": "heal_pawn",
        "id": f"heal_{username}_{int(time.time())}",
        "username": username
    }
    async with get_commands_lock():
        get_pending().append(cmd)
    await _db_enqueue_command(cmd)
    return {"success": True, "message": f"💊 Лечение! -{HEAL_COST}💎"}

@router.get("/api/rimworld/heal-cooldown/{username}")
async def get_heal_cooldown(username: str):
    now = time.time()
    last_heal = await _get_last_heal_ts(username)
    elapsed = now - last_heal
    left = max(0, int(HEAL_COOLDOWN_SECONDS - elapsed))
    return {"cooldown_left": left}

@router.post("/api/rimworld/resurrect-pawn")
async def resurrect_pawn(request: Request):
    if err := await _require_stream_live():
        return err
    db = get_db()
    # JWT-защита: имя зрителя из подписанного JWT, не из body.
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    username, channel_id = auth

    RESURRECT_COST = 500
    balance = await db.get_points(username)
    if balance < RESURRECT_COST:
        return {"success": False, "message": f"Нужно {RESURRECT_COST}💎, у тебя {balance}💎"}

    if not await db.remove_points(username, RESURRECT_COST):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}
    cmd = {
        "type": "resurrect_pawn",
        "id": f"resurrect_{username}_{int(time.time())}",
        "username": username
    }
    async with get_commands_lock():
        get_pending().append(cmd)
    await _db_enqueue_command(cmd)
    return {"success": True, "message": f"✨ Воскрешение! -{RESURRECT_COST}💎"}



# ===== ГЕНЫ (BIOTECH) =====

@router.post("/api/rimworld/reset-progressive/{username}/{category}")
async def reset_progressive_counter(username: str, category: str,
                                    admin=Depends(require_admin)):
    """
    Сбросить счётчик прогрессивных покупок зрителя.
    category: 'trait' | 'gene' | 'all'
    Только для администратора.
    """
    db = get_db()
    if category not in ("trait", "gene", "all"):
        return {"success": False, "message": "category должен быть trait, gene или all"}

    cats = ["trait", "gene"] if category == "all" else [category]
    async with aiosqlite.connect(db.db_path) as conn:
        for cat in cats:
            await conn.execute(
                "DELETE FROM purchase_counters WHERE username = ? AND category = ?",
                (username.lower(), cat)
            )
        await conn.commit()

    return {"success": True, "message": f"Счётчик {'всех категорий' if category == 'all' else category} сброшен для {username}"}


@router.get("/api/rimworld/progressive-price/{username}/{category}")
async def get_progressive_price(username: str, category: str):
    """
    Возвращает текущую прогрессивную цену следующей покупки черты или гена.
    category: 'trait' | 'gene'
    Ответ: { count, next_price, base_price }
    """
    db = get_db()
    BASE_PRICES = {"trait": 1000, "gene": 1000}
    base = BASE_PRICES.get(category, 1000)
    count = await db.get_purchase_count(username, category)
    next_price = db.calc_progressive_price(base, count)
    return {
        "username": username,
        "category": category,
        "count": count,
        "next_price": next_price,
        "base_price": base,
    }


@router.post("/api/rimworld/buy-gene")
async def buy_gene(request: Request):
    """Зритель покупает ген — прогрессивная цена: 1-й=1000, 2-й=2000, ..."""
    if err := await _require_stream_live():
        return err
    # JWT-защита: имя зрителя из подписанного JWT (не из body), channel_id тоже.
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    username, channel_id = auth

    db = get_db()
    data = await request.json()
    def_name = data.get('def_name') or data.get('item_def')
    if not username or not def_name:
        return {"success": False, "message": "Неверные параметры"}

    # Базовая цена из конфига прогрессии (не из shop_catalog)
    BASE_GENE_PRICE = 1000
    count = await db.get_purchase_count(username, "gene")
    price = db.calc_progressive_price(BASE_GENE_PRICE, count)
    # Берём label из каталога если есть
    label = def_name
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute(
            "SELECT label FROM shop_catalog WHERE def_name = ?", (def_name,))
        row = await cursor.fetchone()
        if row and row[0]:
            label = row[0]

    balance = await db.get_points(username)
    if balance < price:
        return {"success": False, "message": f"Недостаточно очков! Нужно {price}💎 (ген №{count+1}), у тебя {balance}💎"}

    if not await db.remove_points(username, price):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}
    # Инкрементируем счётчик ПОСЛЕ списания (атомарность: если remove_points упал — счётчик не трогаем)
    await db.increment_purchase_count(username, "gene")

    cmd = {
        "type": "add_gene",
        "id": f"gene_{username}_{int(time.time())}",
        "username": username,
        "def_name": def_name,
    }
    async with get_commands_lock():
        get_pending().append(cmd)
    await _db_enqueue_command(cmd)
    return {"success": True, "message": f"🧬 Ген «{label}» добавляется! -{price}💎 (ген №{count+1})"}



# ===== СТРАСТЬ (PASSION) =====

# Цены: None→Minor (⭐) и Minor→Major (🔥)
PASSION_PRICES = {
    0: 500,   # None → Minor (⭐): дёшево
    1: 1500,  # Minor → Major (🔥): дороже
}
# Сброс страсти (любой уровень → None)
PASSION_RESET_PRICE = 300

# Стандартные defName навыков RimWorld → читаемые названия (fallback если нет в каталоге)
SKILL_LABELS = {
    "Shooting":     "Стрельба",
    "Melee":        "Ближний бой",
    "Construction": "Строительство",
    "Mining":       "Добыча",
    "Cooking":      "Готовка",
    "Plants":       "Растениеводство",
    "Animals":      "Животноводство",
    "Crafting":     "Ремесло",
    "Artistic":     "Искусство",
    "Medicine":     "Медицина",
    "Social":       "Социальность",
    "Intellectual": "Интеллект",
}


@router.get("/api/rimworld/pawn-skills/{username}")
async def get_pawn_skills(username: str):
    """
    Текущие навыки пешки зрителя с уровнями страсти.
    Используется для отображения выбора огонька в UI.
    """
    from main import sanitize_username as _san
    username = _san(username)
    if not username:
        return {"skills": []}

    async with aiosqlite.connect(get_db().db_path) as conn:
        # Находим pawn_id
        cursor = await conn.execute(
            "SELECT id FROM rimworld_pawns WHERE username = ? AND is_alive = 1", (username,))
        row = await cursor.fetchone()
        if not row:
            return {"skills": [], "error": "Пешка не найдена"}
        pawn_id = row[0]

        cursor = await conn.execute("""
            SELECT skill_name, skill_level, passion, is_disabled
            FROM rimworld_pawn_skills
            WHERE pawn_id = ?
            ORDER BY skill_level DESC, skill_name
        """, (pawn_id,))
        rows = await cursor.fetchall()

    skills = []
    for r in rows:
        skill_name, level, passion, is_disabled = r
        label = SKILL_LABELS.get(skill_name, skill_name)
        # Цена следующего апгрейда (None если уже максимум или навык отключён)
        upgrade_price = None if is_disabled or passion >= 2 else PASSION_PRICES.get(passion)
        skills.append({
            "def_name":      skill_name,
            "label":         label,
            "level":         level,
            "passion":       passion,
            "is_disabled":   bool(is_disabled),
            "upgrade_price": upgrade_price,
            "reset_price":   PASSION_RESET_PRICE if passion > 0 and not is_disabled else None,
        })
    return {"skills": skills}


@router.post("/api/rimworld/buy-passion")
async def buy_passion(request: Request):
    """
    Купить/повысить огонёк страсти для навыка пешки.
    Тело: { username, skill_def, passion } где passion = желаемый уровень (1 или 2).
    Цена: 500💎 за ⭐ (0→1), 1500💎 за 🔥 (1→2).
    Нельзя перескочить через уровень (0→2 не работает).
    """
    if err := await _require_stream_live():
        return err
    # JWT-защита: имя зрителя из подписанного JWT (не из body), channel_id тоже.
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    username, channel_id = auth

    db = get_db()
    data = await request.json()

    skill_def = data.get('skill_def', '').strip()
    passion   = int(data.get('passion', 1))

    if not username or not skill_def:
        return {"success": False, "message": "Неверные параметры"}
    if passion not in (1, 2):
        return {"success": False, "message": "passion должен быть 1 (⭐) или 2 (🔥)"}

    # Проверяем текущую страсть у пешки
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute(
            "SELECT id FROM rimworld_pawns WHERE username = ? AND is_alive = 1", (username,))
        row = await cursor.fetchone()
        if not row:
            return {"success": False, "message": "Пешка не найдена — создай её сначала!"}
        pawn_id = row[0]

        cursor = await conn.execute(
            "SELECT passion, is_disabled FROM rimworld_pawn_skills WHERE pawn_id = ? AND skill_name = ?",
            (pawn_id, skill_def))
        skill_row = await cursor.fetchone()

    if not skill_row:
        return {"success": False, "message": f"Навык '{skill_def}' не найден у пешки"}

    current_passion, is_disabled = skill_row
    if is_disabled:
        return {"success": False, "message": "Этот навык недоступен для пешки (несовместимая черта)"}
    if current_passion >= passion:
        icons = {0: "—", 1: "⭐", 2: "🔥"}
        return {"success": False, "message": f"Страсть уже {icons.get(current_passion, current_passion)} — нельзя понизить через покупку"}
    if passion - current_passion > 1:
        return {"success": False, "message": "Нельзя перепрыгнуть через уровень — сначала купи ⭐, потом 🔥"}

    price = PASSION_PRICES.get(current_passion, 500)
    balance = await db.get_points(username)
    if balance < price:
        icons = {1: "⭐", 2: "🔥"}
        return {"success": False, "message": f"Нужно {price}💎 для {icons.get(passion, passion)}, у тебя {balance}💎"}

    if not await db.remove_points(username, price):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}

    label = SKILL_LABELS.get(skill_def, skill_def)
    icons = {1: "⭐", 2: "🔥"}
    cmd = {
        "type":      "set_passion",
        "id":        f"passion_{username}_{int(time.time())}",
        "username":  username,
        "skill_def": skill_def,
        "passion":   passion,
    }
    async with get_commands_lock():
        get_pending().append(cmd)
    await _db_enqueue_command(cmd)
    return {"success": True, "message": f"{icons[passion]} {label}: страсть повышена! -{price}💎"}


@router.post("/api/rimworld/reset-passion")
async def reset_passion(request: Request):
    """Сбросить страсть к навыку до None (0). Стоимость 300💎."""
    if err := await _require_stream_live():
        return err
    db = get_db()
    # JWT-защита: имя зрителя из подписанного JWT, не из body.
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    username, channel_id = auth

    data = await request.json()
    skill_def = data.get('skill_def', '').strip()

    if not username or not skill_def:
        return {"success": False, "message": "Неверные параметры"}

    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute(
            "SELECT id FROM rimworld_pawns WHERE username = ? AND is_alive = 1", (username,))
        row = await cursor.fetchone()
        if not row:
            return {"success": False, "message": "Пешка не найдена"}
        pawn_id = row[0]

        cursor = await conn.execute(
            "SELECT passion, is_disabled FROM rimworld_pawn_skills WHERE pawn_id = ? AND skill_name = ?",
            (pawn_id, skill_def))
        skill_row = await cursor.fetchone()

    if not skill_row or skill_row[0] == 0:
        return {"success": False, "message": "Страсти нет — сбрасывать нечего"}
    if skill_row[1]:
        return {"success": False, "message": "Навык недоступен"}

    balance = await db.get_points(username)
    if balance < PASSION_RESET_PRICE:
        return {"success": False, "message": f"Нужно {PASSION_RESET_PRICE}💎 для сброса страсти"}

    if not await db.remove_points(username, PASSION_RESET_PRICE):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}
    label = SKILL_LABELS.get(skill_def, skill_def)
    cmd = {
        "type":      "set_passion",
        "id":        f"passion_reset_{username}_{int(time.time())}",
        "username":  username,
        "skill_def": skill_def,
        "passion":   0,
    }
    async with get_commands_lock():
        get_pending().append(cmd)
    await _db_enqueue_command(cmd)
    return {"success": True, "message": f"— {label}: страсть сброшена! -{PASSION_RESET_PRICE}💎"}


# ===== ЧЕРТЫ =====

@router.post("/api/rimworld/buy-trait")
async def buy_trait(request: Request):
    """Зритель покупает черту — прогрессивная цена: 1-я=1000, 2-я=2000, ..."""
    if err := await _require_stream_live():
        return err
    # JWT-защита: имя зрителя из подписанного JWT (не из body), channel_id тоже.
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    username, channel_id = auth
    db = get_db()
    data = await request.json()
    trait_def = data.get('trait_def')
    degree    = int(data.get('degree', 0))
    label     = data.get('label', trait_def)

    if not username or not trait_def:
        return {"success": False, "message": "Неверные параметры"}

    # Прогрессивная цена — НЕ из каталога, считаем по счётчику зрителя
    BASE_TRAIT_PRICE = 1000
    count = await db.get_purchase_count(username, "trait")
    trait_cost = db.calc_progressive_price(BASE_TRAIT_PRICE, count)

    # Берём label из каталога если есть
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute(
            "SELECT label FROM shop_catalog WHERE def_name = ? OR def_name = ? LIMIT 1",
            (f"{trait_def}:{degree}", trait_def))
        row = await cursor.fetchone()
        if row and row[0]:
            label = row[0]

    balance = await db.get_points(username)
    if balance < trait_cost:
        return {"success": False, "message": f"Нужно {trait_cost}💎 (черта №{count+1}), у тебя {balance}💎"}

    if not await db.remove_points(username, trait_cost):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}
    # Инкрементируем счётчик ПОСЛЕ успешного списания
    await db.increment_purchase_count(username, "trait")

    cmd = {
        "type": "add_trait",
        "id": f"trait_{username}_{int(time.time())}",
        "username": username,
        "trait_def": trait_def,
        "degree": degree,
    }
    async with get_commands_lock():
        get_pending().append(cmd)
    await _db_enqueue_command(cmd)
    return {"success": True, "message": f"🧬 Черта «{label}» добавляется! -{trait_cost}💎 (черта №{count+1})"}

@router.post("/api/rimworld/remove-trait")
async def remove_trait(request: Request):
    if err := await _require_stream_live():
        return err
    db = get_db()
    # JWT-защита: имя зрителя из подписанного JWT, не из body.
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    username, channel_id = auth
    data = await request.json()
    trait_def = data.get('trait_def')
    label     = data.get('label', trait_def)

    REMOVE_COST = 300
    balance = await db.get_points(username)
    if balance < REMOVE_COST:
        return {"success": False, "message": f"Нужно {REMOVE_COST}💎"}

    if not await db.remove_points(username, REMOVE_COST):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}
    cmd = {
        "type": "remove_trait",
        "id": f"rmtrait_{username}_{int(time.time())}",
        "username": username,
        "trait_def": trait_def,
    }
    async with get_commands_lock():
        get_pending().append(cmd)
    await _db_enqueue_command(cmd)
    return {"success": True, "message": f"🧬 Черта «{label}» удаляется! -{REMOVE_COST}💎"}


# ===== ВСŠПЕШКИ (для админки) =====



@router.post("/api/rimworld/remove-gene")
async def remove_gene(request: Request):
    """Зритель удаляет ксеноген (включая неактивные/подавленные). Стоимость 3000💎."""
    if err := await _require_stream_live():
        return err
    db = get_db()
    # JWT-защита: имя зрителя из подписанного JWT, не из body.
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    username, channel_id = auth
    data = await request.json()
    gene_def = data.get('gene_def') or data.get('def_name', '')
    label    = data.get('label', gene_def) or gene_def

    if not username or not gene_def:
        return {"success": False, "message": "Неверные параметры"}

    REMOVE_COST = 3000
    balance = await db.get_points(username)
    if balance < REMOVE_COST:
        return {"success": False, "message": f"Нужно {REMOVE_COST}💎 для удаления гена"}

    if not await db.remove_points(username, REMOVE_COST):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}

    # Уменьшаем счётчик покупок генов (не ниже 0) — при удалении следующий ген будет дешевле
    current_count = await db.get_purchase_count(username, "gene")
    if current_count > 0:
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute(
                "UPDATE purchase_counters SET count = count - 1 WHERE username = ? AND category = 'gene' AND count > 0",
                (username.lower(),))
            await conn.commit()

    cmd = {
        "type": "remove_gene",
        "id": f"rmgene_{username}_{int(time.time())}",
        "username": username,
        "def_name": gene_def,
    }
    async with get_commands_lock():
        get_pending().append(cmd)
    await _db_enqueue_command(cmd)
    return {"success": True, "message": f"🧬 Ген «{label}» удаляется! -{REMOVE_COST}💎"}


# ===== АЛИАСЫ ДЛЯ СОВМЕСТИМОСТИ =====
@router.post("/api/rimworld/buy-implant")
async def buy_implant_alias(request: Request):
    """Установка импланта. part_hint='left'|'right'|'' — выбор стороны для парных."""
    if err := await _require_stream_live():
        return err
    # JWT-защита: имя зрителя из подписанного JWT (не из body), channel_id тоже.
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    username, channel_id = auth

    db = get_db()
    data = await request.json()
    def_name  = data.get('item_def') or data.get('def_name')
    part_hint = data.get('part_hint', '')   # 'left' | 'right' | ''

    if not username or not def_name:
        return {"success": False, "message": "Неверные параметры"}

    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute(
            "SELECT price, label, extra_json FROM shop_catalog WHERE def_name = ?", (def_name,))
        item = await cursor.fetchone()

    if not item:
        return {"success": False, "message": "Предмет не найден в каталоге"}

    price, label, extra_json = item
    balance = await db.get_points(username)
    if balance < price:
        return {"success": False, "message": f"Нужно {price}💎, у тебя {balance}💎"}

    if not await db.remove_points(username, price):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}

    side_str = ""
    if part_hint == "left":
        side_str = " (левая)"
    elif part_hint == "right":
        side_str = " (правая)"

    # Сервер больше не угадывает body_part по ключевым словам —
    # мод сам знает точную часть тела и получает part_hint напрямую.
    # InstallImplant в PawnManager.cs резолвит left/right в BodyPartRecord.
    cmd = {
        "type": "install_implant",
        "id": f"implant_{username}_{int(time.time())}",
        "username": username,
        "def_name": def_name,
        "part_hint": part_hint,   # '' | 'left' | 'right'
    }

    async with get_commands_lock():
        get_pending().append(cmd)
    await _db_enqueue_command(cmd)
    try:
        from main import bot as _bot
        asyncio.create_task(_bot.check_and_unlock_achievements(username, 'rimworld_buy'))
    except Exception:
        pass
    return {"success": True, "message": f"🔧 {label}{side_str} устанавливается! -{price}💎"}


@router.post("/api/rimworld/train-skill")
async def train_skill_alias(request: Request):
    """Алиас для buy-item с category=neurotrainer"""
    if err := await _require_stream_live():
        return err
    # JWT-защита: имя зрителя из подписанного JWT (не из body), channel_id тоже.
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    username, channel_id = auth

    db = get_db()
    data = await request.json()
    def_name = data.get('item_def') or data.get('def_name')

    if not username or not def_name:
        return {"success": False, "message": "Неверные параметры"}

    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute(
            "SELECT price, label FROM shop_catalog WHERE def_name = ?", (def_name,))
        item = await cursor.fetchone()

    if not item:
        return {"success": False, "message": "Нейротренер не найден в каталоге"}

    price, label = item
    balance = await db.get_points(username)
    if balance < price:
        return {"success": False, "message": f"Нужно {price}💎, у тебя {balance}💎"}

    if not await db.remove_points(username, price):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}
    cmd = {
        "type": "train_skill",
        "id": f"train_{username}_{int(time.time())}",
        "username": username,
        "def_name": def_name,
    }
    async with get_commands_lock():
        get_pending().append(cmd)
    await _db_enqueue_command(cmd)
    return {"success": True, "message": f"рџ§  {label} применяется! -{price}💎"}

@router.get("/api/rimworld/all-pawns")
async def get_all_pawns(_admin: str = Depends(require_admin)):
    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute("""
            SELECT username, pawn_name, is_alive, ROUND(health * 100) as health
            FROM rimworld_pawns ORDER BY pawn_name
        """)
        rows = await cursor.fetchall()
    return [{"username": r[0], "pawn_name": r[1],
             "is_alive": bool(r[2]), "health": r[3] or 0} for r in rows]

@router.post("/api/rimworld/pawn-gone")
async def pawn_gone(request: Request, _admin: str = Depends(require_admin)):
    db = get_db()
    data = await request.json()
    username = data.get('username')
    if not username:
        return {"status": "error"}
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute(
            "SELECT id FROM rimworld_pawns WHERE username = ?", (username,))
        row = await cursor.fetchone()
        if row:
            pid = row[0]
            for tbl in ["rimworld_pawn_equipment", "rimworld_pawn_skills",
                        "rimworld_pawn_hediffs", "rimworld_pawn_traits", "rimworld_pawn_genes"]:
                await conn.execute(f"DELETE FROM {tbl} WHERE pawn_id = ?", (pid,))
            await conn.execute("DELETE FROM rimworld_pawns WHERE id = ?", (pid,))
            await conn.commit()
    return {"status": "ok"}


# ===== КОЛОНИСТЫ =====

@router.get("/api/rimworld/colonists")
async def get_colonists_all():
    """Список всех пешек (для блока сверху в расширении)"""
    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute("""
            SELECT username, pawn_name, is_alive, ROUND(health * 100) as health
            FROM rimworld_pawns ORDER BY is_alive DESC, pawn_name
        """)
        rows = await cursor.fetchall()
    return {"colonists": [
        {"username": r[0], "pawn_name": r[1], "is_alive": bool(r[2]), "health": r[3] or 0}
        for r in rows
    ]}

@router.get("/api/rimworld/colonists/{username}")
async def get_colonists_by_user(username: str):
    """Колонисты для конкретного зрителя"""
    db = get_db()
    colonists = await db.get_colonists(username)
    return {"colonists": colonists}


# ===== ИВЕНТЫ =====

# Список доступных ивентов — берём из config или хардкодим
@router.post("/api/rimworld/event-catalog")
async def sync_event_catalog(request: Request, _auth=Depends(rimworld_mod_auth)):
    """Мод отправляет каталог ивентов из игры"""
    db = get_db()
    try:
        events = await request.json()
        if not isinstance(events, list):
            return {"success": False, "message": "Expected list"}

        async with aiosqlite.connect(db.db_path) as conn:
            # Пересоздаём таблицу ивентов
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_event_catalog (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    cost INTEGER,
                    cmd TEXT,
                    params TEXT,
                    category TEXT
                )
            """)
            await conn.execute("DELETE FROM rimworld_event_catalog")
            for ev in events:
                await conn.execute(
                    "INSERT INTO rimworld_event_catalog (id, name, cost, cmd, params, category) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        ev.get("id", ""),
                        ev.get("name", ""),
                        int(ev.get("cost", 100)),
                        ev.get("cmd", "fire_incident"),
                        json.dumps(ev.get("params", {})),
                        ev.get("category", "Misc"),
                    )
                )
            await conn.commit()

        print(f"✅ Event catalog synced: {len(events)} events")
        return {"success": True, "count": len(events)}
    except Exception as e:
        print(f"❌ event-catalog error: {e}")
        return {"success": False, "message": str(e)}


@router.get("/api/rimworld/events")
async def get_events():
    """Возвращает каталог ивентов из БД (заполняется модом)"""
    db = get_db()
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_event_catalog (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    cost INTEGER,
                    cmd TEXT,
                    params TEXT,
                    category TEXT
                )
            """)
            cursor = await conn.execute(
                "SELECT id, name, cost, category FROM rimworld_event_catalog ORDER BY category, name"
            )
            rows = await cursor.fetchall()
        return {"events": [{"id": r[0], "name": r[1], "cost": r[2], "category": r[3] or ""} for r in rows]}
    except Exception:
        return {"events": []}


@router.post("/api/rimworld/trigger-event")
async def trigger_event(request: Request):
    if err := await _require_stream_live():
        return err
    db = get_db()
    # JWT-защита: имя зрителя из подписанного JWT, не из body.
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    username, channel_id = auth
    try:
        data = await request.json()
        event_id = data.get("event_id")

        if not username or not event_id:
            return {"success": False, "message": "Неверные параметры"}

        # Берём ивент из БД
        async with aiosqlite.connect(db.db_path) as conn:
            cursor = await conn.execute(
                "SELECT name, cost, cmd, params FROM rimworld_event_catalog WHERE id = ?",
                (event_id,)
            )
            row = await cursor.fetchone()

        if not row:
            return {"success": False, "message": "Ивент не найден"}

        ev_name, cost, cmd, params_json = row
        params = json.loads(params_json) if params_json else {}

        points = await db.get_points(username)
        if points < cost:
            return {"success": False, "message": f"Нужно {cost}💎"}

        if not await db.remove_points(username, cost):
            return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}

        pending_cmd = {
            "type": cmd,
            "id": f"event_{username}_{int(time.time())}",
            "username": username,
        }
        pending_cmd.update(params)
        async with get_commands_lock():
            get_pending().append(pending_cmd)
        await _db_enqueue_command(pending_cmd)

        return {"success": True, "message": f"{ev_name} активирован! (-{cost}💎)"}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ===== LEGACY / СОВМЕСТИМОСТЬ =====

@router.post("/api/rimworld/command")
async def rimworld_command_legacy(request: Request):
    """Старый эндпоинт команды — для совместимости"""
    return {"status": "ok"}

@router.get("/api/rimworld/get-commands")
async def get_commands_legacy(_auth=Depends(rimworld_mod_auth)):
    """Алиас для /api/rimworld/commands"""
    async with get_commands_lock():
        return await _get_commands_inner()

@router.post("/api/rimworld/confirm-commands")
async def confirm_commands(_admin: str = Depends(require_admin)):
    return {"status": "ok"}

@router.post("/api/rimworld/event-result")
async def rimworld_event_result(request: Request, _auth=Depends(rimworld_mod_auth)):
    try:
        data = await request.json()
        print(f"🎲 Результат ивента: {data}")
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/api/rimworld/sync-pawn-death")
async def sync_pawn_death(request: Request, _admin: str = Depends(require_admin)):
    """Обновление статуса пешки (смерть/здоровье)"""
    db = get_db()
    try:
        data = await request.json()
        username = data.get('username')
        is_alive  = data.get('is_alive', True)
        health    = data.get('health', 1.0)
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("""
                UPDATE rimworld_pawns
                SET is_alive=?, health=?, last_sync=CURRENT_TIMESTAMP
                WHERE username=?
            """, (1 if is_alive else 0, health, username))
            await conn.commit()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/api/rimworld/sync-state")
async def sync_rimworld_state(request: Request, _auth=Depends(rimworld_mod_auth)):
    """Массовая синхронизация состояния из мода"""
    db = get_db()
    from dependencies import resolve_channel_id_or_default  # mod endpoint без JWT — TODO M4.5+: HMAC + явный channel_id из мода
    channel_id = resolve_channel_id_or_default()
    try:
        data = await request.json()
        pawns = data.get('pawns', [])
        async with aiosqlite.connect(db.db_path) as conn:
            for p in pawns:
                username = p.get('username')
                if not username:
                    continue
                await conn.execute("""
                    INSERT INTO rimworld_pawns (channel_id, username, pawn_name, is_alive, health, last_sync)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(channel_id, username) DO UPDATE SET
                        pawn_name=excluded.pawn_name,
                        is_alive=excluded.is_alive,
                        health=excluded.health,
                        last_sync=CURRENT_TIMESTAMP
                """, (channel_id, username, p.get('pawn_name',''), 1 if p.get('is_alive',True) else 0, p.get('health',1.0)))
            await conn.commit()
        return {"status": "ok", "received": len(pawns)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ===== ОТЛАДОЧНЫЙ ЭНДПОИНТ =====
@router.get("/api/debug/pawn/{username}")
async def debug_pawn(username: str, _admin: str = Depends(require_admin)):
    """Отладочный endpoint для проверки данных пешки в БД"""
    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT * FROM rimworld_pawns WHERE username = ?",
            (username,)
        )
        pawn = await cursor.fetchone()
        if pawn:
            pawn_dict = dict(pawn)
            # Получаем связанные данные
            cursor = await conn.execute(
                "SELECT * FROM rimworld_pawn_equipment WHERE pawn_id = ?",
                (pawn['id'],)
            )
            pawn_dict['equipment'] = [dict(r) for r in await cursor.fetchall()]
            
            cursor = await conn.execute(
                "SELECT * FROM rimworld_pawn_skills WHERE pawn_id = ?",
                (pawn['id'],)
            )
            pawn_dict['skills'] = [dict(r) for r in await cursor.fetchall()]
            
            cursor = await conn.execute(
                "SELECT * FROM rimworld_pawn_hediffs WHERE pawn_id = ?",
                (pawn['id'],)
            )
            pawn_dict['hediffs'] = [dict(r) for r in await cursor.fetchall()]
            
            cursor = await conn.execute(
                "SELECT * FROM rimworld_pawn_traits WHERE pawn_id = ?",
                (pawn['id'],)
            )
            pawn_dict['traits'] = [dict(r) for r in await cursor.fetchall()]
            
            return pawn_dict
        return {"error": "Pawn not found"}

