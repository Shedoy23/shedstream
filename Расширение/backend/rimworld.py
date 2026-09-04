# rimworld.py — RimWorld legacy routes (1981 line monolith).
#
# Multi-tenant invariant: every RimWorld runtime path is scoped by channel_id.
# The historical tenant-lint skip was removed when the module was reactivated.
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
from datetime import datetime
import aiosqlite
import asyncio
import hashlib
import json
import uuid
import os
import time
import traceback

from config import sanitize_username, RIMWORLD_OFFLINE_TIMEOUT
# require_admin живёт в dependencies (брутфорс-защита + ContextVar channel_id) — раньше тут был
# прокси на main.require_admin, который после переезда падал AttributeError → 500 на всех
# admin-эндпоинтах модуля (лог-триаж 2026-07-04).
from dependencies import (
    require_admin,
    require_jwt_channel,
    require_jwt_user,
    resolve_channel_id_or_default,
)

router = APIRouter()

# ── ЦЕНЫ RimWorld (💎 крустики) ─────────────────────────────────────────────
# 2026-07-24 — ПОДНЯТЫ НА УРОВЕНЬ МОДУЛЯ (были локальными внутри хендлеров).
# Пока они жили внутри функций, отдать их фронту было нельзя — только сделать
# вторую копию. Фронт их и хардкодил, и уже начал врать: кнопка удаления черты
# рисовала 2000💎 при реальных 300 (аудит цен 2026-07-24), а окно сброса страсти
# показывает динамическую цену на кнопке и «300💎» в подтверждении.
# Теперь ОДИН источник: бэк списывает отсюда И отдаёт это же в /api/rimworld/config.
#
# ВНИМАНИЕ: две цены удаления раньше обе назывались REMOVE_COST в разных
# функциях (300 и 3000) — при подъёме одна затёрла бы другую. Разведены по именам.
SPAWN_COST         = 200    # создать пешку
HEAL_COST          = 150    # вылечить
RESURRECT_COST     = 500    # воскресить
TRAIT_REMOVE_COST  = 300    # убрать черту
GENE_REMOVE_COST   = 3000   # убрать ген
BASE_GENE_PRICE    = 1000   # база прогрессивной цены гена  (цена = base × (куплено+1))
BASE_TRAIT_PRICE   = 1000   # база прогрессивной цены черты (та же формула)


# ── Security 2.1 (2026-06-12): RimWorld mod-ingest auth ──────────────────────
# 13 mod-side endpoints accepted UNAUTHENTICATED writes (wipe pawns / rig shop
# catalog / inject pawns). Gate them with the module-token — mirrors Bannerlord
# (issue_module_token / verify_module_token in routes/streamer.py).
# A5 (public-gate 2026-07-02): DEFAULT теперь STRICT — RimLink dormant, поэтому
# незачем держать mod-ingest открытым. Все 13 ingest-эндпоинтов + add-command
# требуют валидный module-token (401 иначе). Это закрывает command-injection и
# неаутентифицированные записи на проде. При РЕАКТИВАЦИИ RimWorld: мод должен слать
# Bearer module-token (issue из дашборда), ИЛИ временно RIMWORLD_REQUIRE_TOKEN=0.
# Влияет ТОЛЬКО на mod→backend ingest; вьюверский RimWorld-таб (read-эндпоинты) не задет.
_RIMWORLD_REQUIRE_TOKEN = os.getenv("RIMWORLD_REQUIRE_TOKEN", "1").lower() in ("1", "true", "yes")
_rimworld_soft_warned = False
async def rimworld_mod_auth(request: Request):
    """Verify the RimWorld module-token on a mod-ingest request. Returns the
    token's channel_id when valid; in SOFT mode returns None (allowed) for a
    missing/invalid token, in STRICT mode raises 401."""
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
    claims = None
    if token.startswith("slmod_v1."):
        import manager_auth
        from dependencies import get_db
        try:
            async with get_db()._connect() as conn:
                claims = await manager_auth.verify_module_credential(
                    conn, token, "rimworld"
                )
        except manager_auth.ManagerAuthUnavailable:
            claims = None
    elif token:
        # Legacy short-lived HMAC token remains valid during Manager rollout.
        from routes.streamer import verify_module_token  # lazy import: avoid cycle
        claims = verify_module_token(token)
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

# Импортируем из main контекст (db, bot, pending_commands)
# Используем late-binding чтобы избежать циклических импортов
def get_db():
    import main as _main
    return _main.db

def get_bot():
    import main as _main
    return _main.bot

def get_pending():
    """Deprecated compatibility hook for old tests.

    Runtime delivery is DB-backed and channel-scoped. New code must never append
    here: a process-global list cannot safely serve more than one streamer.
    """
    import main as _main
    return _main.pending_commands

_commands_lock = asyncio.Lock()

def get_commands_lock():
    return _commands_lock

async def _require_stream_live(request=None, channel_id=None):
    """Проверка стрима для rimworld эндпоинтов — через bot из main.

    channel_id резолвится: явный параметр → JWT запроса (require_jwt_channel,
    он же выставляет ContextVar) → ContextVar/legacy внутри _is_stream_live.
    ВАЖНО (fix 2026-06-12): передавай request — guard часто зовётся ДО auth в
    хендлере, и без этого channel_id был «not resolvable» → проверка падала
    («не удалось проверить статус стрима») на всех RimWorld-действиях.

    Возвращает dict с ошибкой если стрим недоступен или проверка упала,
    None — если стрим живой.

    RimWorld-only production switch: RIMWORLD_REQUIRE_STREAM_LIVE=false
    разрешает технический прогон с запущенной игрой без Twitch-эфира, не снимая
    stream gate с остальных модулей. Общий TESTING_BYPASS_STREAM_LIVE остаётся
    только тестовым аварийным bypass."""
    from config import RIMWORLD_REQUIRE_STREAM_LIVE, TESTING_BYPASS_STREAM_LIVE
    if TESTING_BYPASS_STREAM_LIVE or not RIMWORLD_REQUIRE_STREAM_LIVE:
        return None
    if channel_id is None and request is not None:
        channel_id = require_jwt_channel(request)
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
    # 2026-07-22: схема ПРИВЕДЕНА к той, что создаёт мультитенантная миграция m1
    # (channel_id NOT NULL + UNIQUE(channel_id, cmd_id)). Раньше здесь была
    # досетевая схема без channel_id: на уже мигрированной базе CREATE TABLE IF
    # NOT EXISTS не срабатывал, а INSERT из _db_enqueue_command не передавал
    # channel_id → NOT NULL нарушался и «OR IGNORE» ГЛОТАЛ строку молча.
    # Итог: очередь не сохранилась НИ РАЗУ с момента m1 (на проде 0 строк),
    # обещание «переживёт рестарт сервера» не выполнялось, а рефанд-механика
    # 2026-07-19 физически не могла работать — ей не из чего возвращать.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS rimworld_pending_commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            cmd_id TEXT NOT NULL,
            cmd_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            dedup_key TEXT,
            UNIQUE(channel_id, cmd_id)
        )
    """)
    # 2026-07-19 refund: строки живут до ack (раньше удалялись при выдаче моду
    # → цену вернуть было неоткуда). status: queued → delivered → (удаляется
    # на ack; delivered старше _DELIVERED_STALE_SEC = мод умер → авто-рефанд).
    cur = await conn.execute("PRAGMA table_info(rimworld_pending_commands)")
    cols = {r[1] for r in await cur.fetchall()}
    if "status" not in cols:
        await conn.execute(
            "ALTER TABLE rimworld_pending_commands ADD COLUMN status TEXT DEFAULT 'queued'")
    # M98 — отпечаток команды для распознавания двойного клика.
    if "dedup_key" not in cols:
        await conn.execute(
            "ALTER TABLE rimworld_pending_commands ADD COLUMN dedup_key TEXT")
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rw_cmds_dedup "
        "ON rimworld_pending_commands(channel_id, dedup_key, created_at)")
    if "delivered_at" not in cols:
        await conn.execute(
            "ALTER TABLE rimworld_pending_commands ADD COLUMN delivered_at REAL")


# Доставленная моду команда без ack дольше этого срока считается потерянной
# (мод крашнулся/закрыт до выполнения) → авто-рефанд. Мод поллит каждые 15с,
# ack уходит сразу после выполнения — 10 минут это уже труп.
_DELIVERED_STALE_SEC = 600


async def _refund_cmd_row_tx(conn, channel_id: int, cmd_id: str,
                             cmd_json: str, reason: str) -> bool:
    """Возврат очков за невыполненную команду. На переданном conn, БЕЗ commit —
    вызывающий держит транзакцию (возврат + DELETE строки = атомарно, повторный
    ack не найдёт строку → двойного возврата нет)."""
    try:
        cmd = json.loads(cmd_json)
    except Exception as _je:
        print(f"DBG refund json fail: {_je!r} raw={cmd_json!r}")
        return False
    price = int(cmd.get("price") or 0)
    username = (cmd.get("username") or "").strip()
    cmd_channel_id = int(cmd.get("channel_id") or 0)
    if cmd_channel_id != int(channel_id):
        raise RuntimeError(
            f"RimWorld command {cmd_id!r} channel mismatch: "
            f"row={channel_id}, payload={cmd_channel_id}"
        )
    if price <= 0 or not username:
        # Команды до 2026-07-19 без price/channel_id — вернуть нечего/некому.
        print(f"DBG refund guard: price={price} user={username!r} ch={channel_id!r} raw={cmd_json[:120]!r}")
        return False
    await get_db().add_points_tx(conn, username, price, channel_id)

    # 2026-07-25 — вернуть НЕ ТОЛЬКО деньги, но и цену.
    # Гены и черты продаются по прогрессивной цене: счётчик покупок растёт при
    # покупке (increment_purchase_count) и удорожает следующую. Раньше рефанд
    # возвращал крустики, а счётчик оставлял поднятым → зритель видел «деньги
    # вернули, всё честно», но его следующий ген навсегда стоил дороже за
    # покупку, которой не было. Связать одно с другим он не мог: рефанд сегодня,
    # переплата через неделю. Откат идёт на ТОМ ЖЕ conn → одна транзакция с
    # возвратом денег.
    _PROGRESSIVE = {"add_gene": "gene", "add_trait": "trait"}
    category = _PROGRESSIVE.get(cmd.get("type"))
    if category:
        await get_db().decrement_purchase_count_tx(conn, username, category, channel_id)
        print(f"↩️  RimWorld refund: счётчик {category} для @{username} откачен")

    print(f"💸 RimWorld refund: @{username} +{price}💎 (cmd={cmd_id}, reason={reason})")
    return True


async def _refund_stale_delivered(conn, channel_id: int):
    """Авто-рефанд команд, доставленных моду, но не подтверждённых слишком долго
    (мод крашнулся между выдачей и выполнением). Вызывается под commands_lock."""
    cutoff = time.time() - _DELIVERED_STALE_SEC
    cur = await conn.execute(
        "SELECT cmd_id, cmd_json FROM rimworld_pending_commands "
        "WHERE channel_id=? AND status='delivered' "
        "AND delivered_at IS NOT NULL AND delivered_at < ?",
        (channel_id, cutoff))
    rows = await cur.fetchall()
    for cmd_id, cmd_json in rows:
        await _refund_cmd_row_tx(
            conn, channel_id, cmd_id, cmd_json, "stale_delivered")
        await conn.execute(
            "DELETE FROM rimworld_pending_commands "
            "WHERE channel_id=? AND cmd_id=?",
            (channel_id, cmd_id))

async def _db_enqueue_command(cmd: dict):
    """Сохранить команду в БД (переживёт рестарт сервера)"""
    db = get_db()
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            await _ensure_pending_commands_table(conn)
            # 2026-07-22: channel_id обязателен (NOT NULL после m1). Все 12 мест
            # постановки команд его передают — проверено. Если вдруг нет, лучше
            # шумно отказаться, чем молча потерять команду, за которую заплатили.
            channel_id = cmd.get('channel_id')
            if channel_id is None:
                print(f"❌ db_enqueue: команда {cmd.get('id')!r} без channel_id — "
                      f"НЕ сохранена (переживёт только до рестарта сервера)")
                return
            # БЕЗ "OR IGNORE": именно оно превращало нарушение NOT NULL в тихую
            # потерю строки и прятало этот баг с самой миграции m1.
            cur = await conn.execute(
                "INSERT INTO rimworld_pending_commands (channel_id, cmd_id, cmd_json) "
                "VALUES (?, ?, ?)",
                (channel_id, cmd.get('id', ''), json.dumps(cmd, ensure_ascii=False))
            )
            if not cur.rowcount:
                print(f"⚠️ db_enqueue: строка {cmd.get('id')!r} не вставилась")
            await conn.commit()
    except Exception as e:
        # Дубль по UNIQUE(channel_id, cmd_id) — норма при ретрае, остальное — беда.
        print(f"⚠️ db_enqueue {cmd.get('id')!r}: {type(e).__name__}: {e}")

# Окно, в котором два одинаковых запроса считаются одним кликом. Три секунды —
# компромисс, выбранный по поведению человека: дабл-клик и повторная отправка
# укладываются в доли секунды, а осознанная вторая покупка того же предмета
# требует увидеть подтверждение и снова прицелиться — это дольше. Ставить
# больше опасно: зритель, который правда хочет купить два одинаковых предмета
# подряд, не должен упереться в нашу защиту.
DEDUP_WINDOW_SEC = 3


def _dedup_key(cmd: dict) -> str:
    """Отпечаток команды без служебного поля `id`.

    Два клика по одной кнопке дают побайтово одинаковую команду — отличается
    только `id` (в нём метка времени). Значит ключ выводится из содержимого, и
    просить что-либо у фронта не нужно (он заморожен на CDN). Разные покупки
    дают разные отпечатки сами собой: знать про каждый тип команды не требуется,
    новый тип защищён с первого дня.
    """
    payload = {k: v for k, v in cmd.items() if k != "id"}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


async def _charge_and_enqueue(username: str, channel_id: int, price: int,
                              cmd: dict, on_success=None) -> bool:
    """Списать крустики И поставить команду моду — ОДНОЙ транзакцией.

    2026-07-26 (этап 2 переезда RimWorld). Раньше это были два независимых
    коммита: `db.remove_points(...)` на своём соединении, потом
    `_db_enqueue_command(...)` на другом. Падение или ошибка БД между ними =
    крустики списаны, команды нет, вернуть нечего даже теоретически — в базе не
    осталось следа, что зритель за что-то платил. У Bannerlord это давно
    закрыто (`add_points_tx`/`remove_points_tx` на conn вызывающего), у RimWorld
    оставалось по-старому.

    Теперь: одно `BEGIN IMMEDIATE`, внутри — списание, вставка команды и
    необязательное действие вызывающего (`on_success(conn)` — например рост
    счётчика прогрессивных цен). Либо всё, либо ничего.

    Возвращает False, если не хватило баланса (транзакция откатана, зритель не
    потерял ничего). Исключения пробрасываются — молча терять деньги нельзя.

    В память (`get_pending()`) команда кладётся ТОЛЬКО после успешного commit:
    иначе мод мог бы получить команду, которой нет в базе, и та потерялась бы
    на рестарте.
    """
    db = get_db()
    channel_id = int(channel_id)
    # Token/JWT-derived channel is ground truth. Never trust a caller-provided
    # channel embedded in a command body.
    cmd["channel_id"] = channel_id
    async with aiosqlite.connect(db.db_path) as ddl_conn:
        await _ensure_pending_commands_table(ddl_conn)
        await ddl_conn.commit()

    async with db._connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        try:
            # M98 — двойной клик. Проверка ВНУТРИ транзакции: BEGIN IMMEDIATE
            # держит запись, поэтому второй запрос дождётся первого и увидит
            # его строку. Снаружи транзакции здесь была бы гонка.
            key = _dedup_key(cmd)
            import module_liveness
            use_module_api = await module_liveness.is_on_air(
                db, channel_id, "rimworld")
            if use_module_api:
                cur = await conn.execute(
                    "SELECT action_id FROM module_actions "
                    "WHERE channel_id=? AND module_id='rimworld' "
                    "AND json_extract(data, '$._dedup_key')=? "
                    "AND created_at > datetime('now', ?)",
                    (channel_id, key, "-%d seconds" % DEDUP_WINDOW_SEC))
            else:
                cur = await conn.execute(
                    "SELECT cmd_id FROM rimworld_pending_commands "
                    "WHERE channel_id = ? AND dedup_key = ? "
                    "  AND created_at > datetime('now', ?)",
                    (channel_id, key, "-%d seconds" % DEDUP_WINDOW_SEC))
            twin = await cur.fetchone()
            if twin:
                # Покупка уже идёт. Откатываем и отвечаем УСПЕХОМ: зритель нажал
                # дважды на то, что сработало, — показывать ошибку неправильно.
                # Списания второй раз не происходит.
                await conn.execute("ROLLBACK")
                print(f"↩️  RimWorld: повторный клик @{username} "
                      f"({cmd.get('type')}) — не списываю, уже в очереди "
                      f"как {twin[0]}")
                return True
            if not await db.remove_points_tx(conn, username, price, channel_id):
                await conn.execute("ROLLBACK")
                return False

            # Идентификатор команды обязан быть уникальным. Вызывающие строят
            # его как f"gene_{username}_{int(time.time())}" — с точностью до
            # СЕКУНДЫ, поэтому две РАЗНЫЕ покупки в одну секунду сталкивались на
            # UNIQUE(channel_id, cmd_id). Раньше это молча съедало команду
            # (`_db_enqueue_command` глотал исключение), а деньги оставались
            # списанными. Дописываем короткий уникальный хвост: за повтор клика
            # теперь отвечает dedup_key, а cmd_id должен просто не повторяться.
            cmd["id"] = "%s_%s" % (cmd.get("id", "cmd"), uuid.uuid4().hex[:6])
            if use_module_api:
                action_data = dict(cmd)
                action_data.pop("id", None)
                action_data["price"] = int(price)
                action_data["initiated_by"] = username.lower()
                action_data["_dedup_key"] = key
                await conn.execute(
                    "INSERT INTO module_actions "
                    "(channel_id,module_id,action_id,type,data,status) "
                    "VALUES (?,'rimworld',?,?,?,'queued')",
                    (channel_id, cmd["id"], cmd.get("type", ""),
                     json.dumps(action_data, ensure_ascii=False)))
            else:
                await conn.execute(
                    "INSERT INTO rimworld_pending_commands "
                    "(channel_id, cmd_id, cmd_json, dedup_key) "
                    "VALUES (?, ?, ?, ?)",
                    (channel_id, cmd["id"],
                     json.dumps(cmd, ensure_ascii=False), key))
            if on_success is not None:
                await on_success(conn)
            await conn.commit()
        except Exception:
            try:
                await conn.execute("ROLLBACK")
            except Exception:
                pass
            raise

    return True


async def _ensure_heal_cooldowns_table(conn):
    """Создаёт таблицу кулдаунов лечения если её нет."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS rimworld_heal_cooldowns (
            channel_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            last_heal_ts REAL NOT NULL,
            PRIMARY KEY (channel_id, username)
        )
    """)

async def _get_last_heal_ts(username: str, channel_id: int) -> float:
    """Получить timestamp последнего лечения (0 если нет данных)."""
    db = get_db()
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            await _ensure_heal_cooldowns_table(conn)
            cur = await conn.execute(
                "SELECT last_heal_ts FROM rimworld_heal_cooldowns "
                "WHERE channel_id = ? AND username = ?",
                (channel_id, username.lower())
            )
            row = await cur.fetchone()
            return float(row[0]) if row else 0.0
    except Exception as e:
        print(f"⚠️ get_heal_ts: {e}")
        return 0.0

async def _set_last_heal_ts(username: str, ts: float, channel_id: int):
    """Сохранить timestamp последнего лечения."""
    db = get_db()
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            await _ensure_heal_cooldowns_table(conn)
            await conn.execute("""
                INSERT INTO rimworld_heal_cooldowns (channel_id, username, last_heal_ts)
                VALUES (?, ?, ?)
                ON CONFLICT(channel_id, username) DO UPDATE SET last_heal_ts = excluded.last_heal_ts
            """, (channel_id, username.lower(), float(ts)))
            await conn.commit()
    except Exception as e:
        print(f"⚠️ set_heal_ts: {e}")

async def _db_dequeue_commands(channel_id: int):
    """Достать невыданные команды из БД (восстановление после рестарта).

    2026-07-19 refund: строки НЕ удаляем — они помечаются delivered при выдаче
    моду (_get_commands_inner) и удаляются только на ack/stale-рефанде."""
    db = get_db()
    result = []
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            await _ensure_pending_commands_table(conn)
            cursor = await conn.execute(
                "SELECT cmd_json FROM rimworld_pending_commands "
                "WHERE channel_id=? AND (status='queued' OR status IS NULL) "
                "ORDER BY id LIMIT 50",
                (channel_id,))
            rows = await cursor.fetchall()
            for row in rows:
                try:
                    result.append(json.loads(row[0]))
                except Exception:
                    pass
            if result:
                print(f"♻️ Восстановлено {len(result)} команд из БД после рестарта")
    except Exception as e:
        print(f"⚠️ db_dequeue: {e}")
    return result

# ===== ГЛОБАЛЬНЫЕ =====
# Heartbeat is runtime state, but it is still tenant state. Keying by channel
# prevents one running colony from making every streamer's RimWorld tab online.
rimworld_last_heartbeat: dict[int, datetime] = {}
# RIMWORLD_OFFLINE_TIMEOUT импортируется из config.py


# ===== СТАТУС =====

def _require_viewer_channel(request: Request) -> int:
    """Вернуть tenant из Twitch JWT или честно отклонить публичное чтение."""
    channel_id = require_jwt_channel(request)
    if not channel_id:
        raise HTTPException(status_code=401, detail="Twitch authorization required")
    return int(channel_id)


@router.get("/api/rimworld/status")
async def rimworld_status(request: Request):
    """Статус подключения RimWorld"""
    channel_id = _require_viewer_channel(request)
    last_heartbeat = rimworld_last_heartbeat.get(channel_id)
    if last_heartbeat is None:
        return {"online": False}
    elapsed = (datetime.utcnow() - last_heartbeat).total_seconds()
    return {"online": elapsed < RIMWORLD_OFFLINE_TIMEOUT, "last_seen": int(elapsed)}

@router.post("/api/rimworld/heartbeat")
async def rimworld_heartbeat(mod_channel_id=Depends(rimworld_mod_auth)):
    channel_id = resolve_channel_id_or_default(mod_channel_id)
    rimworld_last_heartbeat[channel_id] = datetime.utcnow()
    import module_liveness
    await module_liveness.touch(get_db(), channel_id, "rimworld")
    return {"status": "ok"}

@router.post("/api/rimworld/offline")
async def rimworld_offline(mod_channel_id=Depends(rimworld_mod_auth)):
    channel_id = resolve_channel_id_or_default(mod_channel_id)
    rimworld_last_heartbeat.pop(channel_id, None)
    import module_liveness
    await module_liveness.clear(get_db(), channel_id, "rimworld")
    return {"status": "ok"}


# ===== СЕССИЯ =====

@router.post("/api/rimworld/session-start")
async def rimworld_session_start(mod_channel_id=Depends(rimworld_mod_auth)):
    """Вызывается при загрузке игры — очищает старых пешек"""
    channel_id = resolve_channel_id_or_default(mod_channel_id)
    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM rimworld_pawns WHERE channel_id=?",
            (channel_id,))
        count = (await cursor.fetchone())[0]
        cursor2 = await conn.execute(
            "SELECT id FROM rimworld_pawns WHERE channel_id=?",
            (channel_id,))
        rows = await cursor2.fetchall()
        for row in rows:
            pid = row[0]
            for tbl in ["rimworld_pawn_equipment", "rimworld_pawn_skills",
                        "rimworld_pawn_hediffs", "rimworld_pawn_traits", "rimworld_pawn_genes"]:
                await conn.execute(f"DELETE FROM {tbl} WHERE pawn_id = ?", (pid,))
        await conn.execute(
            "DELETE FROM rimworld_pawns WHERE channel_id=?", (channel_id,))
        await conn.commit()
    print(f"🔄 [ch={channel_id}] Session start: очищено {count} пешек")
    return {"status": "ok", "cleared": count}


# ===== СИНХРОНИЗАЦИЯ ПЕШКИ =====

@router.post("/api/rimworld/sync-pawn")
async def sync_pawn(request: Request,
                    mod_channel_id=Depends(rimworld_mod_auth)):
    """Синхронизация одной пешки с детальными данными"""
    db = get_db()
    channel_id = resolve_channel_id_or_default(mod_channel_id)
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
                    "SELECT id FROM rimworld_pawns "
                    "WHERE channel_id=? AND username=?",
                    (channel_id, username))
                row = await cursor.fetchone()
                if row:
                    # Помечаем мёртвой, НЕ удаляем — расширение должно показать кнопку воскрешения
                    await conn.execute(
                        "UPDATE rimworld_pawns SET is_alive=0 "
                        "WHERE channel_id=? AND username=?",
                        (channel_id, username))
                    await conn.commit()
            return {"status": "ok", "action": "marked_dead"}

        print(f"📥 Синхронизация пешки {username} ({pawn_name}), alive={is_alive}")

        async with aiosqlite.connect(db.db_path) as conn:
            # Создаём таблицы если нет
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_pawns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    pawn_name TEXT,
                    is_alive INTEGER DEFAULT 1,
                    health REAL DEFAULT 1.0,
                    world_id TEXT,
                    world_name TEXT,
                    last_sync TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(channel_id, username)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_pawn_traits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
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
                    channel_id INTEGER NOT NULL,
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
                    channel_id INTEGER NOT NULL,
                    pawn_id INTEGER,
                    body_part TEXT,
                    hediff_label TEXT,
                    severity REAL DEFAULT 0,
                    age_ticks INTEGER DEFAULT 0
                )
            """)

            # Ищем существующую пешку
            cursor = await conn.execute(
                "SELECT id FROM rimworld_pawns "
                "WHERE channel_id=? AND username=?",
                (channel_id, username))
            old_row = await cursor.fetchone()

            if old_row:
                pawn_id = old_row[0]
                # Обновляем основные данные
                await conn.execute("""
                    UPDATE rimworld_pawns
                    SET pawn_name=?, is_alive=?, health=?, world_id=?, world_name=?, last_sync=CURRENT_TIMESTAMP
                    WHERE channel_id=? AND id=?
                """, (pawn_name, 1 if is_alive else 0, health, world_id,
                      world_name, channel_id, pawn_id))
            else:
                # Новая пешка
                await conn.execute("""
                    INSERT INTO rimworld_pawns
                    (channel_id, username, pawn_name, is_alive, health, world_id, world_name)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (channel_id, username, pawn_name, 1 if is_alive else 0,
                      health, world_id, world_name))
                cursor = await conn.execute(
                    "SELECT id FROM rimworld_pawns "
                    "WHERE channel_id=? AND username=?",
                    (channel_id, username))
                row = await cursor.fetchone()
                if not row:
                    return {"status": "error", "message": "Failed to get pawn ID"}
                pawn_id = row[0]

            # Очищаем старые данные
            for tbl in PAWN_DATA_TABLES:
                await conn.execute(
                    f"DELETE FROM {tbl} WHERE channel_id=? AND pawn_id=?",
                    (channel_id, pawn_id))

            # --- Экипировка ---
            for eq in data.get('equipment', []):
                meta = {k: eq.get(k) for k in (
                    'max_hp', 'quality', 'stuff', 'description', 'color',
                    'weapon_traits', 'psi_abilities', 'is_bladelink'
                ) if eq.get(k) not in (None, '', [], {})}
                await conn.execute("""
                    INSERT INTO rimworld_pawn_equipment
                    (channel_id, pawn_id, slot, item_def, item_name, hp, meta)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    channel_id,
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
                    channel_id INTEGER NOT NULL,
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
                    (channel_id, pawn_id, skill_name, skill_level, passion, xp, is_disabled)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    channel_id,
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
                    INSERT INTO rimworld_pawn_traits
                    (channel_id, pawn_id, trait_def, degree, label, trait_desc)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (channel_id, pawn_id, tdef, t.get('degree', 0),
                      t.get('label', ''), t.get('desc', '')))

            # --- Хедиффы (раны, болезни) ---
            for h in data.get('hediffs', []):
                label = str(h.get('label', h.get('hediff_label', ''))).strip()
                if not label:
                    continue
                await conn.execute("""
                    INSERT INTO rimworld_pawn_hediffs
                    (channel_id, pawn_id, body_part, hediff_label, severity, age_ticks)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    channel_id,
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
                         hediff_def, part_def, is_paired, is_left, channel_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    channel_id,
                ))

            # --- Гены (Biotech) ---
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_pawn_genes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
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
                    INSERT INTO rimworld_pawn_genes
                    (channel_id, pawn_id, def_name, label, is_active, xenogene, gene_class)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    channel_id,
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
async def get_my_pawn(username: str, request: Request):
    """Получить полную информацию о пешке зрителя.

    Public-gate (2026-07-02): требует JWT, и зритель может смотреть ТОЛЬКО свою
    пешку. Раньше endpoint был без auth — любой по логину читал полный профиль
    чужой пешки (экипировка/раны/трейты/гены). Без JWT или чужой логин →
    {exists:false, auth_required:true}: фронт рисует состояние «создать пешку»,
    вкладка «Интеграция» для ревьюера не ломается.
    """
    auth = require_jwt_user(request)
    if not auth:
        return {"exists": False, "auth_required": True}
    jwt_login, channel_id = auth
    if sanitize_username(username) != jwt_login:
        return {"exists": False, "auth_required": True}
    db = get_db()
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            cursor = await conn.execute("""
                SELECT id, pawn_name, is_alive, health, world_id, world_name
                FROM rimworld_pawns WHERE channel_id=? AND username=?
            """, (channel_id, username))
            pawn = await cursor.fetchone()

            if not pawn:
                return {"exists": False}

            pawn_id = pawn[0]

            # Экипировка (+ meta JSON с weapon_traits/psi/quality/и т.д.)
            cursor = await conn.execute("""
                SELECT slot, item_def, item_name, hp, meta
                FROM rimworld_pawn_equipment
                WHERE channel_id=? AND pawn_id=?
            """, (channel_id, pawn_id))
            equipment = await cursor.fetchall()

            # Навыки с is_disabled
            cursor = await conn.execute("""
                SELECT skill_name,
                       CASE WHEN COALESCE(is_disabled, 0) = 1 THEN 0 ELSE MAX(skill_level, 0) END,
                       passion, xp,
                       COALESCE(is_disabled, 0)
                FROM rimworld_pawn_skills WHERE channel_id=? AND pawn_id=?
                ORDER BY skill_level DESC
            """, (channel_id, pawn_id))
            skills = await cursor.fetchall()

            # Черты
            traits = []
            try:
                cursor = await conn.execute("""
                    SELECT trait_def, degree, label, trait_desc
                    FROM rimworld_pawn_traits
                    WHERE channel_id=? AND pawn_id=?
                """, (channel_id, pawn_id))
                traits = await cursor.fetchall()
            except Exception:
                pass

            # Хедиффы
            cursor = await conn.execute("""
                SELECT body_part, hediff_label, severity, age_ticks,
                       hediff_def, part_def, is_paired, is_left
                FROM rimworld_pawn_hediffs WHERE pawn_id = ?
                  AND channel_id=?
            """, (pawn_id, channel_id))
            hediffs = await cursor.fetchall()

            # Гены
            genes = []
            try:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS rimworld_pawn_genes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        channel_id INTEGER NOT NULL,
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
                    FROM rimworld_pawn_genes
                    WHERE channel_id=? AND pawn_id=?
                    ORDER BY xenogene DESC, label
                """, (channel_id, pawn_id))
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
async def sync_pawns_bulk(request: Request, mod_channel_id=Depends(rimworld_mod_auth)):
    """Массовая синхронизация пешек (правильная версия)"""
    db = get_db()
    from dependencies import resolve_channel_id_or_default
    channel_id = resolve_channel_id_or_default(mod_channel_id)
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
                    await conn.execute(
                        f"DELETE FROM {tbl} WHERE channel_id=? AND pawn_id=?",
                        (channel_id, pawn_id))
                
                # Сохраняем экипировку (с meta-JSON для weapon_traits/psi/quality/...)
                for eq in pawn_data.get('equipment', []):
                    meta = {k: eq.get(k) for k in (
                        'max_hp', 'quality', 'stuff', 'description', 'color',
                        'weapon_traits', 'psi_abilities', 'is_bladelink'
                    ) if eq.get(k) not in (None, '', [], {})}
                    await conn.execute("""
                        INSERT INTO rimworld_pawn_equipment
                        (channel_id, pawn_id, slot, item_def, item_name, hp, meta)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        channel_id,
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
                        (channel_id, pawn_id, skill_name, skill_level, passion, xp, is_disabled)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        channel_id,
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
                        INSERT INTO rimworld_pawn_traits
                        (channel_id, pawn_id, trait_def, degree, label, trait_desc)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        channel_id,
                        pawn_id,
                        trait.get('def_name', ''),
                        trait.get('degree', 0),
                        trait.get('label', ''),
                        trait.get('desc', '')
                    ))
                
                # Сохраняем хедиффы
                for hediff in pawn_data.get('hediffs', []):
                    await conn.execute("""
                        INSERT INTO rimworld_pawn_hediffs
                        (channel_id, pawn_id, body_part, hediff_label, severity, age_ticks)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        channel_id,
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
                             hediff_def, part_def, is_paired, is_left, channel_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        channel_id,
                    ))

                # Сохраняем гены (Biotech)
                for g in pawn_data.get('genes', []):
                    def_n = g.get('def_name', '')
                    if not def_n:
                        continue
                    await conn.execute("""
                        INSERT INTO rimworld_pawn_genes
                        (channel_id, pawn_id, def_name, label, is_active, xenogene, gene_class)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        channel_id,
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
async def get_commands(mod_channel_id=Depends(rimworld_mod_auth)):
    """Мод забирает команды для выполнения"""
    channel_id = resolve_channel_id_or_default(mod_channel_id)
    async with get_commands_lock():
        return await _get_commands_inner(channel_id)

async def _get_commands_inner(channel_id: int):
    """Atomically deliver queued commands for one module-token channel."""
    channel_id = int(channel_id)
    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        await _ensure_pending_commands_table(conn)
        await conn.execute("BEGIN IMMEDIATE")
        try:
            # Refund only this channel's abandoned deliveries. A poll by B must
            # never mutate A's balances or queue.
            await _refund_stale_delivered(conn, channel_id)
            cursor = await conn.execute(
                "SELECT cmd_id, cmd_json FROM rimworld_pending_commands "
                "WHERE channel_id=? AND (status='queued' OR status IS NULL) "
                "ORDER BY id LIMIT 50",
                (channel_id,))
            rows = await cursor.fetchall()
            cmds = []
            cmd_ids = []
            for cmd_id, raw in rows:
                try:
                    cmd = json.loads(raw)
                except Exception as exc:
                    raise RuntimeError(
                        f"invalid queued RimWorld command {cmd_id!r}") from exc
                if int(cmd.get("channel_id") or 0) != channel_id:
                    raise RuntimeError(
                        f"queued RimWorld command {cmd_id!r} has foreign channel")
                if not cmd.get("type"):
                    raise RuntimeError(
                        f"queued RimWorld command {cmd_id!r} has no type")
                cmds.append(cmd)
                cmd_ids.append(cmd_id)

            if cmd_ids:
                placeholders = ",".join("?" for _ in cmd_ids)
                await conn.execute(
                    "UPDATE rimworld_pending_commands "
                    "SET status='delivered', delivered_at=? "
                    f"WHERE channel_id=? AND cmd_id IN ({placeholders})",
                    [time.time(), channel_id] + cmd_ids)
                await conn.execute(
                    "UPDATE manager_diagnostic_actions SET status='delivered' "
                    f"WHERE channel_id=? AND command_id IN ({placeholders}) "
                    "AND status='queued'",
                    [channel_id] + cmd_ids)
            await conn.commit()
            return cmds
        except Exception:
            try:
                await conn.execute("ROLLBACK")
            except Exception:
                pass
            raise


@router.post("/api/rimworld/ack-command")
async def ack_command(request: Request,
                      mod_channel_id=Depends(rimworld_mod_auth)):
    """2026-07-19 refund: раньше ack только печатался — success=false ничего не
    делал, зритель молча терял очки за невыполненную команду. Теперь:
    success=true → строка очереди удаляется; success=false → возврат цены
    зрителю + удаление, в ОДНОЙ транзакции (повторный ack не найдёт строку →
    идемпотентно, двойного возврата нет)."""
    data = await request.json()
    channel_id = resolve_channel_id_or_default(mod_channel_id)
    cmd_id = (data.get('command_id') or '').strip()
    success = bool(data.get('success'))
    message = str(data.get('message') or '')
    print(f"{'✅' if success else '❌'} Команда {cmd_id}: success={success}"
          + (f" ({message})" if message else ""))
    if not cmd_id:
        return {"status": "error", "acked": False, "refunded": False,
                "message": "command_id required"}

    db = get_db()
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            await _ensure_pending_commands_table(conn)
            await conn.execute("BEGIN IMMEDIATE")
            cur = await conn.execute(
                "SELECT cmd_json FROM rimworld_pending_commands "
                "WHERE channel_id=? AND cmd_id=?",
                (channel_id, cmd_id))
            row = await cur.fetchone()
            if row is None:
                # Уже обработан (идемпотентный повтор) или древний id — no-op.
                await conn.execute("ROLLBACK")
                return {"status": "ok", "acked": False, "refunded": False}
            try:
                command = json.loads(row[0])
            except Exception:
                command = {}
            if command.get("diagnostic_mode") == "lost_ack":
                # Controlled reliability probe: the no-op was executed by the
                # real game, but this boundary behaves like an unavailable ACK
                # receiver. Manager expires and removes it after 120 seconds;
                # a later connector retry then receives an idempotent no-op ACK.
                await conn.execute("ROLLBACK")
                print(f"🧪 RimWorld diagnostic: намеренно теряем ACK {cmd_id}")
                raise HTTPException(
                    status_code=503,
                    detail="simulated diagnostic ACK loss",
                )
            refunded = False
            if not success:
                refunded = await _refund_cmd_row_tx(
                    conn, channel_id, cmd_id, row[0],
                    message or "mod_refused")
            diagnostic_id = str(command.get("diagnostic_id") or "")
            if diagnostic_id:
                await conn.execute(
                    "UPDATE manager_diagnostic_actions "
                    "SET status=?,completed_at=?,error=? "
                    "WHERE diagnostic_id=? AND channel_id=? AND command_id=?",
                    (
                        "acked" if success else "failed",
                        time.time(),
                        None if success else (message or "mod_refused")[:512],
                        diagnostic_id,
                        channel_id,
                        cmd_id,
                    ),
                )
            await conn.execute(
                "DELETE FROM rimworld_pending_commands "
                "WHERE channel_id=? AND cmd_id=?",
                (channel_id, cmd_id))
            await conn.commit()
            return {"status": "ok", "acked": True, "refunded": refunded}
    except Exception as e:
        print(f"⚠️ ack-command {cmd_id}: {e}")
        # ACK — часть денежной транзакции. HTTP 200 здесь заставлял старые
        # коннекторы считать ответ доставленным и прекращать ретраи, после чего
        # stale-refund возвращал деньги за уже случившийся игровой эффект.
        raise HTTPException(status_code=503, detail="ack failed")

@router.post("/api/rimworld/commands-processed")
async def commands_processed(request: Request, _auth=Depends(rimworld_mod_auth)):
    """Мод уведомляет о завершении обработки пакета команд"""
    data = await request.json()
    count = data.get('processed', 0)
    print(f"✅ Обработано команд: {count}")
    return {"status": "ok"}

@router.post("/api/rimworld/add-command")
async def add_command(request: Request,
                      mod_channel_id=Depends(rimworld_mod_auth)):
    # Public-gate (2026-07-02): был без auth вообще — любой мог инжектить команды
    # в очередь. Теперь под rimworld_mod_auth (как остальные mod-ingest).
    data = await request.json()
    channel_id = resolve_channel_id_or_default(mod_channel_id)
    if not data.get("type"):
        print(f"⚠️ add-command: отклонена команда без поля 'type': {data}")
        return {"status": "error", "message": "Missing 'type' field"}
    data["channel_id"] = channel_id
    async with get_commands_lock():
        await _db_enqueue_command(data)
    return {"status": "ok"}


# ===== МАГАЗИН / КАТАЛОГ =====

@router.post("/api/rimworld/shop-catalog")
async def receive_shop_catalog(request: Request, _auth=Depends(rimworld_mod_auth)):
    """Принимает каталог предметов от мода"""
    db = get_db()
    from dependencies import resolve_channel_id_or_default
    channel_id = resolve_channel_id_or_default(_auth)
    try:
        items = await request.json()
        if not isinstance(items, list):
            return {"status": "error", "message": "Expected list"}

        async with aiosqlite.connect(db.db_path) as conn:
            # M97: channel_id + UNIQUE(channel_id, def_name). Раньше def_name был
            # глобально уникален — каталог второго стримера перезаписывал бы
            # позиции первого.
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS shop_catalog (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    category TEXT,
                    def_name TEXT,
                    label TEXT,
                    description TEXT,
                    price INTEGER,
                    base_price INTEGER DEFAULT 0,
                    tech_level TEXT,
                    extra_json TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(channel_id, def_name)
                )
            """)
            # Добавляем колонку base_price если её нет (миграция старых БД)
            try:
                await conn.execute("ALTER TABLE shop_catalog ADD COLUMN base_price INTEGER DEFAULT 0")
                await conn.commit()
            except Exception:
                pass  # колонка уже существует
            # M97: БЕЗ WHERE это стирало каталог ВСЕМ стримерам сразу —
            # второй запустил игру, у первого магазин опустел.
            await conn.execute("DELETE FROM shop_catalog WHERE channel_id = ?",
                               (channel_id,))
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
                    (channel_id, category, def_name, label, description, price, base_price, tech_level, extra_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    channel_id,
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

async def _rimworld_is_active(channel_id: int) -> bool:
    """Активен ли модуль RimWorld на этом канале.

    2026-07-26. Каталог RimWorld (1.6 МБ) грузился у КАЖДОГО зрителя при
    открытии расширения — даже когда стример играет в Bannerlord: во фронте
    `loadShopCatalog()` стоит безусловно на старте, ДО того как он вообще
    узнаёт активный модуль. Фронт заморожен на CDN до вердикта Twitch, поэтому
    чиним со стороны бэка: неактивному модулю отдаём пустой каталог.

    Это безопасно ровно потому, что во фронте есть страховка: при переходе на
    вкладку RimWorld он перезагружает каталог, если тот пуст
    (`viewer.js`, обработчик вкладки). Стример переключил модуль посреди стрима —
    зритель откроет вкладку и получит настоящий каталог.

    NULL (модуль не выбран) считаем активным: не ломать каналы, где настройку
    просто не трогали.
    """
    try:
        ch = await get_db().get_channel(channel_id)
    except Exception:
        return True          # не смогли узнать — ведём себя как раньше
    if not ch:
        return True
    active = (ch.get("active_module") or "").strip().lower()
    return active in ("", "rimworld")


@router.get("/api/rimworld/catalog")
async def get_catalog(request: Request, category: str = None,
                      search: str = None, username: str = None):
    """
    Каталог предметов. Если передан username — для черт и генов price заменяется
    на актуальную прогрессивную цену (base_price * (count+1)).
    """
    db = get_db()
    # M97: каталог — на канал. Без этого зритель одного стримера видел бы
    # позиции другого (а после заливки — вообще пустой магазин).
    if username:
        auth = require_jwt_user(request)
        if not auth:
            raise HTTPException(status_code=401, detail="Twitch authorization required")
        jwt_username, channel_id = auth
        if jwt_username.lower() != username.lower():
            raise HTTPException(status_code=403, detail="Cannot read another viewer's prices")
    else:
        channel_id = _require_viewer_channel(request)
    if not await _rimworld_is_active(channel_id):
        # Стример играет в другую игру — 1.6 МБ каталога ему не нужны.
        return {"items": [], "total": 0, "skipped": "module_inactive"}
    async with aiosqlite.connect(db.db_path) as conn:
        query = ("SELECT category, def_name, label, description, price, tech_level, "
                 "extra_json, base_price FROM shop_catalog WHERE channel_id = ?")
        params = [channel_id]
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
        trait_count = await db.get_purchase_count(username, "trait", channel_id)
        gene_count  = await db.get_purchase_count(username, "gene", channel_id)

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
    if err := await _require_stream_live(request):
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
            "SELECT price, label, category FROM shop_catalog "
            "WHERE channel_id = ? AND def_name = ?", (channel_id, def_name))
        item = await cursor.fetchone()

    if not item:
        # 2026-07-22: отказ платного действия обязан называть причину. Раньше
        # молчал — и «предмет не найден» нельзя было отличить от опечатки в
        # def_name, устаревшего каталога или расхождения регистра.
        print(f"🛒 buy-item: def_name={def_name!r} НЕТ в shop_catalog "
              f"(@{username}, ch={channel_id})")
        return {"success": False, "message": "Предмет не найден в каталоге"}

    price, label, category = item
    balance = await db.get_points(username)
    if balance < price:
        return {"success": False, "message": f"Недостаточно очков! Нужно {price}💎, у тебя {balance}💎"}

    # Категорию проверяем ДО списания. Раньше сначала списывали, потом
    # обнаруживали неподдерживаемую категорию и возвращали деньги ОТДЕЛЬНЫМ
    # коммитом — ещё одна щель, в которой они могли пропасть.
    cmd_type = CATEGORY_TO_CMD.get(category)
    if not cmd_type:
        return {"success": False, "message": f"Категория '{category}' не поддерживает покупку через этот эндпоинт"}

    cmd = {
        "type": cmd_type,
        "id": f"buy_{username}_{int(time.time())}",
        "username": username,
        "def_name": def_name,
        # 2026-07-19 refund: цена+канал едут в cmd_json — при ack success=false
        # бэкенд вернёт очки (см. ack_command). Мод лишние поля игнорирует.
        "price": price,
        "channel_id": channel_id,
    }
    if not await _charge_and_enqueue(username, channel_id, price, cmd):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}

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
    if err := await _require_stream_live(request):
        return err
    db = get_db()
    # JWT-защита: имя зрителя из подписанного JWT, не из body.
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    username, channel_id = auth

    balance = await db.get_points(username)
    if balance < SPAWN_COST:
        return {"success": False, "message": f"Нужно {SPAWN_COST}💎, у тебя {balance}💎"}

    cmd = {
        "type": "spawn_pawn",
        "id": f"spawn_{username}_{int(time.time())}",
        "username": username,
        "price": SPAWN_COST,
        "channel_id": channel_id,
    }
    if not await _charge_and_enqueue(username, channel_id, SPAWN_COST, cmd):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}
    return {"success": True, "message": f"✨ Пешка создаётся! -{SPAWN_COST}💎"}

@router.post("/api/rimworld/heal-pawn")
async def heal_pawn(request: Request):
    if err := await _require_stream_live(request):
        return err
    db = get_db()
    # JWT-защита: имя зрителя из подписанного JWT, не из body.
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    username, channel_id = auth

    # Проверяем КД
    now = time.time()
    last_heal = await _get_last_heal_ts(username, channel_id)
    elapsed = now - last_heal
    if elapsed < HEAL_COOLDOWN_SECONDS:
        left = int(HEAL_COOLDOWN_SECONDS - elapsed)
        mins, secs = divmod(left, 60)
        return {"success": False, "cooldown_left": left,
                "message": f"⏳ Лечение будет доступно через {mins}:{secs:02d}"}

    balance = await db.get_points(username)
    if balance < HEAL_COST:
        return {"success": False, "message": f"Нужно {HEAL_COST}💎, у тебя {balance}💎"}

    cmd = {
        "type": "heal_pawn",
        "id": f"heal_{username}_{int(time.time())}",
        "username": username,
        "price": HEAL_COST,
        "channel_id": channel_id,
    }

    # Кулдаун ставим ВНУТРИ той же транзакции: иначе сбой между списанием и
    # записью кулдауна дал бы бесплатное лечение (или наоборот — кулдаун без
    # лечения).
    async def _mark_cooldown(conn):
        await conn.execute(
            "INSERT INTO rimworld_heal_cooldowns (channel_id, username, last_heal_ts) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(channel_id, username) DO UPDATE SET last_heal_ts = excluded.last_heal_ts",
            (channel_id, username.lower(), float(now)))

    if not await _charge_and_enqueue(username, channel_id, HEAL_COST, cmd,
                                     on_success=_mark_cooldown):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}
    return {"success": True, "message": f"💊 Лечение! -{HEAL_COST}💎"}

@router.get("/api/rimworld/heal-cooldown/{username}")
async def get_heal_cooldown(username: str, request: Request):
    auth = require_jwt_user(request)
    if not auth:
        raise HTTPException(status_code=401, detail="Twitch authorization required")
    jwt_username, channel_id = auth
    if jwt_username.lower() != username.lower():
        raise HTTPException(status_code=403, detail="Cannot read another viewer's cooldown")
    now = time.time()
    last_heal = await _get_last_heal_ts(jwt_username, channel_id)
    elapsed = now - last_heal
    left = max(0, int(HEAL_COOLDOWN_SECONDS - elapsed))
    return {"cooldown_left": left}

@router.post("/api/rimworld/resurrect-pawn")
async def resurrect_pawn(request: Request):
    if err := await _require_stream_live(request):
        return err
    db = get_db()
    # JWT-защита: имя зрителя из подписанного JWT, не из body.
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "❌ Требуется авторизация Twitch"}
    username, channel_id = auth

    balance = await db.get_points(username)
    if balance < RESURRECT_COST:
        return {"success": False, "message": f"Нужно {RESURRECT_COST}💎, у тебя {balance}💎"}

    cmd = {
        "type": "resurrect_pawn",
        "id": f"resurrect_{username}_{int(time.time())}",
        "username": username,
        "price": RESURRECT_COST,
        "channel_id": channel_id,
    }
    if not await _charge_and_enqueue(username, channel_id, RESURRECT_COST, cmd):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}
    return {"success": True, "message": f"✨ Воскрешение! -{RESURRECT_COST}💎"}



# ===== ГЕНЫ (BIOTECH) =====

@router.post("/api/rimworld/reset-progressive/{username}/{category}")
async def reset_progressive_counter(username: str, category: str,
                                    admin=Depends(require_admin)):
    # M97: админская ручка — канал по умолчанию (админ работает по своему).
    from dependencies import resolve_channel_id_or_default
    channel_id = resolve_channel_id_or_default()
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
                "DELETE FROM purchase_counters "
                "WHERE channel_id = ? AND username = ? AND category = ?",
                (channel_id, username.lower(), cat)
            )
        await conn.commit()

    return {"success": True, "message": f"Счётчик {'всех категорий' if category == 'all' else category} сброшен для {username}"}


@router.get("/api/rimworld/progressive-price/{username}/{category}")
async def get_progressive_price(request: Request, username: str, category: str):
    """
    Возвращает текущую прогрессивную цену следующей покупки черты или гена.
    category: 'trait' | 'gene'
    Ответ: { count, next_price, base_price }
    """
    db = get_db()
    auth = require_jwt_user(request)
    if not auth:
        raise HTTPException(status_code=401, detail="Twitch authorization required")
    jwt_username, channel_id = auth
    if jwt_username.lower() != username.lower():
        raise HTTPException(status_code=403, detail="Cannot read another viewer's prices")
    BASE_PRICES = {"trait": 1000, "gene": 1000}
    base = BASE_PRICES.get(category, 1000)
    count = await db.get_purchase_count(username, category, channel_id)
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
    if err := await _require_stream_live(request):
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
    count = await db.get_purchase_count(username, "gene", channel_id)
    price = db.calc_progressive_price(BASE_GENE_PRICE, count)
    # Берём label из каталога если есть
    label = def_name
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute(
            "SELECT label FROM shop_catalog WHERE channel_id = ? AND def_name = ?",
            (channel_id, def_name))
        row = await cursor.fetchone()
        if row and row[0]:
            label = row[0]

    balance = await db.get_points(username)
    if balance < price:
        return {"success": False, "message": f"Недостаточно очков! Нужно {price}💎 (ген №{count+1}), у тебя {balance}💎"}

    cmd = {
        "type": "add_gene",
        "id": f"gene_{username}_{int(time.time())}",
        "username": username,
        "def_name": def_name,
        "price": price,
        "channel_id": channel_id,
    }

    # Счётчик прогрессивных цен растёт ВНУТРИ той же транзакции. Раньше он был
    # отдельным коммитом сразу после списания: сбой между ними давал либо
    # покупку без удорожания, либо удорожание без покупки.
    async def _bump_gene(conn):
        await conn.execute(
            "INSERT INTO purchase_counters (channel_id, username, category, count) "
            "VALUES (?, ?, 'gene', 1) "
            "ON CONFLICT(channel_id, username, category) DO UPDATE SET count = count + 1",
            (channel_id, username.lower()))

    if not await _charge_and_enqueue(username, channel_id, price, cmd,
                                     on_success=_bump_gene):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}
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
async def get_pawn_skills(username: str, request: Request):
    """
    Текущие навыки пешки зрителя с уровнями страсти.
    Используется для отображения выбора огонька в UI.
    """
    auth = require_jwt_user(request)
    if not auth:
        return {"skills": []}
    jwt_login, channel_id = auth
    username = sanitize_username(username)
    if not username or username != jwt_login:
        return {"skills": []}

    async with aiosqlite.connect(get_db().db_path) as conn:
        # Находим pawn_id
        cursor = await conn.execute(
            "SELECT id FROM rimworld_pawns "
            "WHERE channel_id=? AND username=? AND is_alive=1",
            (channel_id, username))
        row = await cursor.fetchone()
        if not row:
            return {"skills": [], "error": "Пешка не найдена"}
        pawn_id = row[0]

        cursor = await conn.execute("""
            SELECT skill_name, skill_level, passion, is_disabled
            FROM rimworld_pawn_skills
            WHERE channel_id=? AND pawn_id=?
            ORDER BY skill_level DESC, skill_name
        """, (channel_id, pawn_id))
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
    if err := await _require_stream_live(request):
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
            "SELECT id FROM rimworld_pawns "
            "WHERE channel_id=? AND username=? AND is_alive=1",
            (channel_id, username))
        row = await cursor.fetchone()
        if not row:
            return {"success": False, "message": "Пешка не найдена — создай её сначала!"}
        pawn_id = row[0]

        cursor = await conn.execute(
            "SELECT passion, is_disabled FROM rimworld_pawn_skills "
            "WHERE channel_id=? AND pawn_id=? AND skill_name=?",
            (channel_id, pawn_id, skill_def))
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

    label = SKILL_LABELS.get(skill_def, skill_def)
    icons = {1: "⭐", 2: "🔥"}
    cmd = {
        "type":      "set_passion",
        "id":        f"passion_{username}_{int(time.time())}",
        "username":  username,
        "skill_def": skill_def,
        "passion":   passion,
        "price":     price,
        "channel_id": channel_id,
    }
    if not await _charge_and_enqueue(username, channel_id, price, cmd):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}
    return {"success": True, "message": f"{icons[passion]} {label}: страсть повышена! -{price}💎"}


@router.post("/api/rimworld/reset-passion")
async def reset_passion(request: Request):
    """Сбросить страсть к навыку до None (0). Стоимость 300💎."""
    if err := await _require_stream_live(request):
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
            "SELECT id FROM rimworld_pawns "
            "WHERE channel_id=? AND username=? AND is_alive=1",
            (channel_id, username))
        row = await cursor.fetchone()
        if not row:
            return {"success": False, "message": "Пешка не найдена"}
        pawn_id = row[0]

        cursor = await conn.execute(
            "SELECT passion, is_disabled FROM rimworld_pawn_skills "
            "WHERE channel_id=? AND pawn_id=? AND skill_name=?",
            (channel_id, pawn_id, skill_def))
        skill_row = await cursor.fetchone()

    if not skill_row or skill_row[0] == 0:
        return {"success": False, "message": "Страсти нет — сбрасывать нечего"}
    if skill_row[1]:
        return {"success": False, "message": "Навык недоступен"}

    balance = await db.get_points(username)
    if balance < PASSION_RESET_PRICE:
        return {"success": False, "message": f"Нужно {PASSION_RESET_PRICE}💎 для сброса страсти"}

    label = SKILL_LABELS.get(skill_def, skill_def)
    cmd = {
        "type":      "set_passion",
        "id":        f"passion_reset_{username}_{int(time.time())}",
        "username":  username,
        "skill_def": skill_def,
        "passion":   0,
        "price":     PASSION_RESET_PRICE,
        "channel_id": channel_id,
    }
    if not await _charge_and_enqueue(username, channel_id, PASSION_RESET_PRICE, cmd):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}
    return {"success": True, "message": f"— {label}: страсть сброшена! -{PASSION_RESET_PRICE}💎"}


# ===== ЧЕРТЫ =====

@router.post("/api/rimworld/buy-trait")
async def buy_trait(request: Request):
    """Зритель покупает черту — прогрессивная цена: 1-я=1000, 2-я=2000, ..."""
    if err := await _require_stream_live(request):
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
    count = await db.get_purchase_count(username, "trait", channel_id)
    trait_cost = db.calc_progressive_price(BASE_TRAIT_PRICE, count)

    # Берём label из каталога если есть
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute(
            "SELECT label FROM shop_catalog WHERE channel_id = ? "
            "AND (def_name = ? OR def_name = ?) LIMIT 1",
            (channel_id, f"{trait_def}:{degree}", trait_def))
        row = await cursor.fetchone()
        if row and row[0]:
            label = row[0]

    balance = await db.get_points(username)
    if balance < trait_cost:
        return {"success": False, "message": f"Нужно {trait_cost}💎 (черта №{count+1}), у тебя {balance}💎"}

    cmd = {
        "type": "add_trait",
        "id": f"trait_{username}_{int(time.time())}",
        "username": username,
        "trait_def": trait_def,
        "degree": degree,
        "price": trait_cost,
        "channel_id": channel_id,
    }

    # Счётчик — внутри той же транзакции (см. buy_gene).
    async def _bump_trait(conn):
        await conn.execute(
            "INSERT INTO purchase_counters (channel_id, username, category, count) "
            "VALUES (?, ?, 'trait', 1) "
            "ON CONFLICT(channel_id, username, category) DO UPDATE SET count = count + 1",
            (channel_id, username.lower()))

    if not await _charge_and_enqueue(username, channel_id, trait_cost, cmd,
                                     on_success=_bump_trait):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}
    return {"success": True, "message": f"🧬 Черта «{label}» добавляется! -{trait_cost}💎 (черта №{count+1})"}

@router.post("/api/rimworld/remove-trait")
async def remove_trait(request: Request):
    if err := await _require_stream_live(request):
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

    balance = await db.get_points(username)
    if balance < TRAIT_REMOVE_COST:
        return {"success": False, "message": f"Нужно {TRAIT_REMOVE_COST}💎"}

    cmd = {
        "type": "remove_trait",
        "id": f"rmtrait_{username}_{int(time.time())}",
        "username": username,
        "trait_def": trait_def,
        "price": TRAIT_REMOVE_COST,
        "channel_id": channel_id,
    }
    if not await _charge_and_enqueue(username, channel_id, TRAIT_REMOVE_COST, cmd):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}
    return {"success": True, "message": f"🧬 Черта «{label}» удаляется! -{TRAIT_REMOVE_COST}💎"}


# ===== ВСŠПЕШКИ (для админки) =====



@router.post("/api/rimworld/remove-gene")
async def remove_gene(request: Request):
    """Зритель удаляет ксеноген (включая неактивные/подавленные). Стоимость 3000💎."""
    if err := await _require_stream_live(request):
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

    balance = await db.get_points(username)
    if balance < GENE_REMOVE_COST:
        return {"success": False, "message": f"Нужно {GENE_REMOVE_COST}💎 для удаления гена"}

    # Уменьшение счётчика — ВНУТРИ той же транзакции: раньше это был отдельный
    # коммит, и сбой между ним и списанием давал либо удаление без удешевления,
    # либо удешевление без удаления.
    async def _drop_gene_counter(conn):
        await conn.execute(
            "UPDATE purchase_counters SET count = count - 1 "
            "WHERE channel_id = ? AND username = ? AND category = 'gene' AND count > 0",
            (channel_id, username.lower()))

    cmd = {
        "type": "remove_gene",
        "id": f"rmgene_{username}_{int(time.time())}",
        "username": username,
        "def_name": gene_def,
        "price": GENE_REMOVE_COST,
        "channel_id": channel_id,
    }
    if not await _charge_and_enqueue(username, channel_id, GENE_REMOVE_COST, cmd,
                                     on_success=_drop_gene_counter):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}
    return {"success": True, "message": f"🧬 Ген «{label}» удаляется! -{GENE_REMOVE_COST}💎"}


# ===== АЛИАСЫ ДЛЯ СОВМЕСТИМОСТИ =====
@router.post("/api/rimworld/buy-implant")
async def buy_implant_alias(request: Request):
    """Установка импланта. part_hint='left'|'right'|'' — выбор стороны для парных."""
    if err := await _require_stream_live(request):
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
            "SELECT price, label, extra_json FROM shop_catalog "
            "WHERE channel_id = ? AND def_name = ?", (channel_id, def_name))
        item = await cursor.fetchone()

    if not item:
        print(f"🛒 buy-implant: def_name={def_name!r} НЕТ в shop_catalog "
              f"(@{username}, ch={channel_id})")
        return {"success": False, "message": "Предмет не найден в каталоге"}

    price, label, extra_json = item
    balance = await db.get_points(username)
    if balance < price:
        return {"success": False, "message": f"Нужно {price}💎, у тебя {balance}💎"}

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
        "price": price,
        "channel_id": channel_id,
    }

    if not await _charge_and_enqueue(username, channel_id, price, cmd):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}
    try:
        from main import bot as _bot
        asyncio.create_task(_bot.check_and_unlock_achievements(username, 'rimworld_buy'))
    except Exception:
        pass
    return {"success": True, "message": f"🔧 {label}{side_str} устанавливается! -{price}💎"}


@router.post("/api/rimworld/train-skill")
async def train_skill_alias(request: Request):
    """Алиас для buy-item с category=neurotrainer"""
    if err := await _require_stream_live(request):
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
            "SELECT price, label FROM shop_catalog "
            "WHERE channel_id = ? AND def_name = ?", (channel_id, def_name))
        item = await cursor.fetchone()

    if not item:
        return {"success": False, "message": "Нейротренер не найден в каталоге"}

    price, label = item
    balance = await db.get_points(username)
    if balance < price:
        return {"success": False, "message": f"Нужно {price}💎, у тебя {balance}💎"}

    cmd = {
        "type": "train_skill",
        "id": f"train_{username}_{int(time.time())}",
        "username": username,
        "def_name": def_name,
        "price": price,
        "channel_id": channel_id,
    }
    if not await _charge_and_enqueue(username, channel_id, price, cmd):
        return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}
    return {"success": True, "message": f"рџ§  {label} применяется! -{price}💎"}

@router.get("/api/rimworld/all-pawns")
async def get_all_pawns(channel_id: int = None,
                        _admin: str = Depends(require_admin)):
    channel_id = resolve_channel_id_or_default(channel_id)
    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute("""
            SELECT username, pawn_name, is_alive, ROUND(health * 100) as health
            FROM rimworld_pawns WHERE channel_id=? ORDER BY pawn_name
        """, (channel_id,))
        rows = await cursor.fetchall()
    return [{"username": r[0], "pawn_name": r[1],
             "is_alive": bool(r[2]), "health": r[3] or 0} for r in rows]

@router.post("/api/rimworld/pawn-gone")
async def pawn_gone(request: Request, channel_id: int = None,
                    _admin: str = Depends(require_admin)):
    channel_id = resolve_channel_id_or_default(channel_id)
    db = get_db()
    data = await request.json()
    username = data.get('username')
    if not username:
        return {"status": "error"}
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute(
            "SELECT id FROM rimworld_pawns "
            "WHERE channel_id=? AND username=?",
            (channel_id, username))
        row = await cursor.fetchone()
        if row:
            pid = row[0]
            for tbl in ["rimworld_pawn_equipment", "rimworld_pawn_skills",
                        "rimworld_pawn_hediffs", "rimworld_pawn_traits", "rimworld_pawn_genes"]:
                await conn.execute(
                    f"DELETE FROM {tbl} WHERE channel_id=? AND pawn_id=?",
                    (channel_id, pid))
            await conn.execute(
                "DELETE FROM rimworld_pawns WHERE channel_id=? AND id=?",
                (channel_id, pid))
            await conn.commit()
    return {"status": "ok"}


# ===== КОЛОНИСТЫ =====

@router.get("/api/rimworld/colonists")
async def get_colonists_all(request: Request):
    """Список всех пешек (для блока сверху в расширении)"""
    channel_id = require_jwt_channel(request)
    if not channel_id:
        return {"colonists": []}
    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        cursor = await conn.execute("""
            SELECT username, pawn_name, is_alive, ROUND(health * 100) as health
            FROM rimworld_pawns WHERE channel_id=?
            ORDER BY is_alive DESC, pawn_name
        """, (channel_id,))
        rows = await cursor.fetchall()
    return {"colonists": [
        {"username": r[0], "pawn_name": r[1], "is_alive": bool(r[2]), "health": r[3] or 0}
        for r in rows
    ]}

@router.get("/api/rimworld/colonists/{username}")
async def get_colonists_by_user(username: str, request: Request):
    """Колонисты для конкретного зрителя"""
    auth = require_jwt_user(request)
    if not auth:
        return {"colonists": []}
    jwt_login, channel_id = auth
    if sanitize_username(username) != jwt_login:
        return {"colonists": []}
    db = get_db()
    colonists = await db.get_colonists(username, channel_id=channel_id)
    return {"colonists": colonists}


# ===== ИВЕНТЫ =====

# Список доступных ивентов — берём из config или хардкодим
@router.post("/api/rimworld/event-catalog")
async def sync_event_catalog(request: Request, _auth=Depends(rimworld_mod_auth)):
    """Мод отправляет каталог ивентов из игры"""
    db = get_db()
    from dependencies import resolve_channel_id_or_default
    channel_id = resolve_channel_id_or_default(_auth)
    try:
        events = await request.json()
        if not isinstance(events, list):
            return {"success": False, "message": "Expected list"}

        async with aiosqlite.connect(db.db_path) as conn:
            # Пересоздаём таблицу ивентов
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_event_catalog (
                    channel_id INTEGER NOT NULL,
                    id TEXT NOT NULL,
                    name TEXT,
                    cost INTEGER,
                    cmd TEXT,
                    params TEXT,
                    category TEXT,
                    PRIMARY KEY (channel_id, id)
                )
            """)
            # M97: без канала это стирало каталог событий ВСЕМ стримерам.
            await conn.execute("DELETE FROM rimworld_event_catalog WHERE channel_id = ?",
                               (channel_id,))
            for ev in events:
                await conn.execute(
                    "INSERT INTO rimworld_event_catalog "
                    "(channel_id, id, name, cost, cmd, params, category) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        channel_id,
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
async def get_events(request: Request):
    """Возвращает каталог ивентов из БД (заполняется модом)"""
    db = get_db()
    channel_id = _require_viewer_channel(request)
    if not await _rimworld_is_active(channel_id):
        return {"events": [], "skipped": "module_inactive"}
    try:
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS rimworld_event_catalog (
                    channel_id INTEGER NOT NULL,
                    id TEXT NOT NULL,
                    name TEXT,
                    cost INTEGER,
                    cmd TEXT,
                    params TEXT,
                    category TEXT,
                    PRIMARY KEY (channel_id, id)
                )
            """)
            cursor = await conn.execute(
                "SELECT id, name, cost, category FROM rimworld_event_catalog "
                "WHERE channel_id = ? ORDER BY category, name", (channel_id,)
            )
            rows = await cursor.fetchall()
        return {"events": [{"id": r[0], "name": r[1], "cost": r[2], "category": r[3] or ""} for r in rows]}
    except Exception:
        return {"events": []}


@router.post("/api/rimworld/trigger-event")
async def trigger_event(request: Request):
    if err := await _require_stream_live(request):
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
                "SELECT name, cost, cmd, params FROM rimworld_event_catalog "
                "WHERE channel_id = ? AND id = ?",
                (channel_id, event_id)
            )
            row = await cursor.fetchone()

        if not row:
            return {"success": False, "message": "Ивент не найден"}

        ev_name, cost, cmd, params_json = row
        params = json.loads(params_json) if params_json else {}

        points = await db.get_points(username)
        if points < cost:
            return {"success": False, "message": f"Нужно {cost}💎"}

        pending_cmd = {
            "type": cmd,
            "id": f"event_{username}_{int(time.time())}",
            "username": username,
        }
        pending_cmd.update(params)
        # 2026-07-19 refund: ПОСЛЕ update(params) — params из каталога не должны
        # затирать цену/канал.
        pending_cmd["price"] = cost
        pending_cmd["channel_id"] = channel_id
        if not await _charge_and_enqueue(username, channel_id, cost, pending_cmd):
            return {"success": False, "message": "Баланс изменился, попробуй ещё раз"}

        return {"success": True, "message": f"{ev_name} активирован! (-{cost}💎)"}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ===== LEGACY / СОВМЕСТИМОСТЬ =====

@router.post("/api/rimworld/command")
async def rimworld_command_legacy(request: Request):
    """Старый эндпоинт команды — для совместимости"""
    return {"status": "ok"}

@router.get("/api/rimworld/get-commands")
async def get_commands_legacy(mod_channel_id=Depends(rimworld_mod_auth)):
    """Алиас для /api/rimworld/commands"""
    channel_id = resolve_channel_id_or_default(mod_channel_id)
    async with get_commands_lock():
        return await _get_commands_inner(channel_id)

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
async def sync_pawn_death(request: Request, channel_id: int = None,
                          _admin: str = Depends(require_admin)):
    """Обновление статуса пешки (смерть/здоровье)"""
    db = get_db()
    channel_id = resolve_channel_id_or_default(channel_id)
    try:
        data = await request.json()
        username = data.get('username')
        is_alive  = data.get('is_alive', True)
        health    = data.get('health', 1.0)
        async with aiosqlite.connect(db.db_path) as conn:
            await conn.execute("""
                UPDATE rimworld_pawns
                SET is_alive=?, health=?, last_sync=CURRENT_TIMESTAMP
                WHERE channel_id=? AND username=?
            """, (1 if is_alive else 0, health, channel_id, username))
            await conn.commit()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/api/rimworld/sync-state")
async def sync_rimworld_state(request: Request, mod_channel_id=Depends(rimworld_mod_auth)):
    """Массовая синхронизация состояния из мода"""
    db = get_db()
    from dependencies import resolve_channel_id_or_default
    channel_id = resolve_channel_id_or_default(mod_channel_id)
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
async def debug_pawn(username: str, channel_id: int = None,
                     _admin: str = Depends(require_admin)):
    """Отладочный endpoint для проверки данных пешки в БД"""
    channel_id = resolve_channel_id_or_default(channel_id)
    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT * FROM rimworld_pawns "
            "WHERE channel_id=? AND username=?",
            (channel_id, username)
        )
        pawn = await cursor.fetchone()
        if pawn:
            pawn_dict = dict(pawn)
            # Получаем связанные данные
            cursor = await conn.execute(
                "SELECT * FROM rimworld_pawn_equipment "
                "WHERE channel_id=? AND pawn_id=?",
                (channel_id, pawn['id'])
            )
            pawn_dict['equipment'] = [dict(r) for r in await cursor.fetchall()]
            
            cursor = await conn.execute(
                "SELECT * FROM rimworld_pawn_skills "
                "WHERE channel_id=? AND pawn_id=?",
                (channel_id, pawn['id'])
            )
            pawn_dict['skills'] = [dict(r) for r in await cursor.fetchall()]
            
            cursor = await conn.execute(
                "SELECT * FROM rimworld_pawn_hediffs "
                "WHERE channel_id=? AND pawn_id=?",
                (channel_id, pawn['id'])
            )
            pawn_dict['hediffs'] = [dict(r) for r in await cursor.fetchall()]
            
            cursor = await conn.execute(
                "SELECT * FROM rimworld_pawn_traits "
                "WHERE channel_id=? AND pawn_id=?",
                (channel_id, pawn['id'])
            )
            pawn_dict['traits'] = [dict(r) for r in await cursor.fetchall()]
            
            return pawn_dict
        return {"error": "Pawn not found"}


@router.get("/api/rimworld/config")
async def rimworld_config():
    """Балансовые числа RimWorld — единый источник для тонкого фронта.

    2026-07-24. Раньше эти цены жили ТОЛЬКО локальными константами внутри
    хендлеров, а фронт держал свои копии — и они начали расходиться: кнопка
    удаления черты рисовала 2000💎 при реальных 300; окно сброса страсти
    показывает динамическую цену на кнопке и захардкоженные «300💎» в
    подтверждении. Теперь фронт обязан рисовать ОТСЮДА, свои константы удалить.

    Публичный: числа не секретны. Бэк по-прежнему сам enforce'ит цену при
    списании — это только для отображения (аналог /api/bannerlord/config).

    Прогрессивные цены (черта/ген) отдаём базой + формулой, а не готовым числом:
    итог зависит от того, сколько зритель уже купил (см. calc_progressive_price).
    """
    return {
        "spawn_cost":        SPAWN_COST,
        "heal_cost":         HEAL_COST,
        "resurrect_cost":    RESURRECT_COST,
        "trait_remove_cost": TRAIT_REMOVE_COST,
        "gene_remove_cost":  GENE_REMOVE_COST,
        # прогрессивные: цена = base × (уже_куплено + 1)
        "progressive": {
            "trait_base": BASE_TRAIT_PRICE,
            "gene_base":  BASE_GENE_PRICE,
            "formula":    "base * (owned + 1)",
        },
        # страсти: ключ = текущий уровень (0 = нет, 1 = малая)
        "passion_upgrade_prices": PASSION_PRICES,
        "passion_reset_price":    PASSION_RESET_PRICE,
    }
