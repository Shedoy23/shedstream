"""
M1: Multi-tenant schema migration.

Цель: каждая TENANT-таблица получает колонку `channel_id INTEGER` чтобы
данные разных стримеров не пересекались. Существующие строки backfill'ятся
текущим `TWITCH_BROADCASTER_ID` из .env (single-tenant пред-история).

Структура миграции:
- Phase 1: ALTER TABLE ADD COLUMN channel_id NOT NULL DEFAULT <broadcaster> — 14 таблиц
- Phase 2: пересоздание таблиц где channel_id должен быть в PRIMARY KEY/UNIQUE — 17 таблиц
- Phase 3: специальная переделка purchase_counters → rimworld_purchase_counters (pawn-scoped FK)
- Phase 4: композитные индексы (channel_id, ...) + удаление старых однотонных

Идемпотентно через `migrations_applied` таблицу — повторные запуски no-op.

Связано с docs/MULTITENANT_PLAN.md (M1).
"""
import os
from typing import Iterable


def _default_channel_id() -> int:
    """Twitch broadcaster ID из .env, для backfill единственного существующего стримера."""
    val = (os.getenv("TWITCH_BROADCASTER_ID") or "").strip()
    if not val.isdigit():
        raise RuntimeError(
            "TWITCH_BROADCASTER_ID не задан в .env или не число — миграция M1 "
            "не может backfill'ить существующие строки. Установи переменную."
        )
    return int(val)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1: ADD COLUMN — таблицы где UNIQUE/PK не затронут (только новая колонка)
# ─────────────────────────────────────────────────────────────────────────────
ADD_COLUMN_TABLES = [
    "drops",
    "marriages",
    "marriage_proposals",
    "activity_stats",
    "chat_stats",
    "market_listings",
    "rimworld_pawn_equipment",
    "rimworld_pawn_skills",
    "rimworld_pawn_hediffs",
    "rimworld_pawn_traits",
    "rimworld_pawn_genes",
    "rimworld_colonists",
    "rimworld_skills",
    "duel_seasons",
    "pending_duels",
]


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2: RECREATE — таблицы где UNIQUE или PRIMARY KEY должны включать channel_id
#
# Каждый dict:
#   table        — имя таблицы
#   new_schema   — полное определение тела CREATE TABLE (без имени)
#   copy_cols    — SELECT-список из старой таблицы, plus_channel=True вставит DEFAULT
#                  channel_id первым (если в new_schema channel_id первый)
#                  иначе нужно в copy_cols явно указать "channel_id_default"
#   skip_if_missing — если таблица отсутствует, пропустить (для опциональных)
# ─────────────────────────────────────────────────────────────────────────────
RECREATE_TABLES = [
    {
        "table": "viewers",
        "new_schema": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            points INTEGER DEFAULT 0,
            last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
            join_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_afk INTEGER DEFAULT 0,
            UNIQUE(channel_id, username)
        """,
        "copy_cols_template": "id, {chan}, username, points, last_seen, join_time, is_afk",
    },
    {
        "table": "inventory",
        "new_schema": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            quantity INTEGER DEFAULT 1,
            UNIQUE(channel_id, username, item_id),
            FOREIGN KEY (item_id) REFERENCES items(id)
        """,
        "copy_cols_template": "id, {chan}, username, item_id, quantity",
    },
    {
        "table": "quests",
        "new_schema": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            quest_type TEXT NOT NULL,
            current_value INTEGER DEFAULT 0,
            target_value INTEGER NOT NULL,
            reward_points INTEGER DEFAULT 0,
            reward_item_id INTEGER,
            completed_at DATETIME,
            day_date TEXT NOT NULL,
            UNIQUE(channel_id, username, quest_type, day_date)
        """,
        "copy_cols_template": (
            "id, {chan}, username, quest_type, current_value, target_value, "
            "reward_points, reward_item_id, completed_at, day_date"
        ),
    },
    {
        "table": "rimworld_pawns",
        "new_schema": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            pawn_name TEXT NOT NULL,
            is_alive INTEGER DEFAULT 1,
            health REAL DEFAULT 1.0,
            world_id TEXT DEFAULT '',
            world_name TEXT DEFAULT '',
            last_sync DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(channel_id, username)
        """,
        "copy_cols_template": (
            "id, {chan}, username, pawn_name, is_alive, health, world_id, world_name, last_sync"
        ),
    },
    {
        "table": "craft_stats",
        "new_schema": """
            channel_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            item_type TEXT NOT NULL,
            crafted_count INTEGER DEFAULT 0,
            PRIMARY KEY (channel_id, username, item_type)
        """,
        "copy_cols_template": "{chan}, username, item_type, crafted_count",
    },
    {
        "table": "user_achievements",
        "new_schema": """
            channel_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            achievement_key TEXT NOT NULL,
            unlocked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (channel_id, username, achievement_key)
        """,
        "copy_cols_template": "{chan}, username, achievement_key, unlocked_at",
    },
    {
        "table": "stream_streaks",
        "new_schema": """
            channel_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            current_streak INTEGER DEFAULT 0,
            max_streak INTEGER DEFAULT 0,
            last_stream_id TEXT DEFAULT '',
            PRIMARY KEY (channel_id, username)
        """,
        "copy_cols_template": "{chan}, username, current_streak, max_streak, last_stream_id",
    },
    {
        "table": "stream_attendance",
        "new_schema": """
            channel_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            stream_id TEXT NOT NULL,
            minutes INTEGER DEFAULT 0,
            claimed INTEGER DEFAULT 0,
            PRIMARY KEY (channel_id, username, stream_id)
        """,
        "copy_cols_template": "{chan}, username, stream_id, minutes, claimed",
    },
    {
        "table": "stream_sessions",
        "new_schema": """
            channel_id INTEGER NOT NULL,
            id TEXT NOT NULL,
            started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            ended_at DATETIME DEFAULT NULL,
            PRIMARY KEY (channel_id, id)
        """,
        "copy_cols_template": "{chan}, id, started_at, ended_at",
    },
    {
        "table": "casino_settings",
        "new_schema": """
            channel_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (channel_id, key)
        """,
        "copy_cols_template": "{chan}, key, value",
    },
    {
        "table": "free_spins_daily",
        "new_schema": """
            channel_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            last_claim TEXT NOT NULL,
            spins_used INTEGER DEFAULT 0,
            PRIMARY KEY (channel_id, username)
        """,
        "copy_cols_template": "{chan}, username, last_claim, spins_used",
    },
    {
        "table": "duel_stats",
        "new_schema": """
            channel_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            elo INTEGER DEFAULT 1100,
            win_streak INTEGER DEFAULT 0,
            season_id INTEGER DEFAULT 1,
            PRIMARY KEY (channel_id, username)
        """,
        "copy_cols_template": "{chan}, username, elo, win_streak, season_id",
    },
    {
        "table": "promocodes",
        "new_schema": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            points INTEGER DEFAULT 0,
            item_def TEXT DEFAULT NULL,
            item_name TEXT DEFAULT NULL,
            max_uses INTEGER DEFAULT 1,
            uses INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(channel_id, code)
        """,
        "copy_cols_template": (
            "id, {chan}, code, points, item_def, item_name, max_uses, uses, created_at"
        ),
    },
    {
        "table": "promo_uses",
        "new_schema": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            username TEXT NOT NULL,
            used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(channel_id, code, username)
        """,
        "copy_cols_template": "id, {chan}, code, username, used_at",
    },
    {
        "table": "streak_rewards",
        "new_schema": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            streak_count INTEGER NOT NULL,
            diamonds_given INTEGER NOT NULL,
            given_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(channel_id, username, streak_count)
        """,
        "copy_cols_template": (
            "id, {chan}, username, streak_count, diamonds_given, given_at"
        ),
    },
    {
        "table": "channel_points_log",
        "new_schema": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            twitch_redemption_id TEXT NOT NULL,
            reward_title TEXT NOT NULL,
            channel_points_spent INTEGER NOT NULL,
            diamonds_given INTEGER NOT NULL,
            redeemed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(channel_id, twitch_redemption_id)
        """,
        "copy_cols_template": (
            "id, {chan}, username, twitch_redemption_id, reward_title, "
            "channel_points_spent, diamonds_given, redeemed_at"
        ),
    },
    {
        "table": "rimworld_pending_commands",
        "new_schema": """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            cmd_id TEXT NOT NULL,
            cmd_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(channel_id, cmd_id)
        """,
        "copy_cols_template": "id, {chan}, cmd_id, cmd_json, created_at",
        "skip_if_missing": True,
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3: специальная переделка purchase_counters → rimworld_purchase_counters
#
# Старая: (username, category) — счётчик покупок per-зритель per-канал
# Новая:  (pawn_id, category)  — счётчик per-пешка-инстанс
#
# При пересоздании текущие строки маппятся через JOIN на rimworld_pawns
# (у одного стримера у каждого username = одна пешка). После backfill'а старая
# таблица удаляется.
# ─────────────────────────────────────────────────────────────────────────────
PURCHASE_COUNTERS_RECREATE = """
    CREATE TABLE IF NOT EXISTS rimworld_purchase_counters (
        pawn_id INTEGER NOT NULL,
        category TEXT NOT NULL,
        count INTEGER DEFAULT 0,
        PRIMARY KEY (pawn_id, category),
        FOREIGN KEY (pawn_id) REFERENCES rimworld_pawns(id) ON DELETE CASCADE
    )
"""


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4: композитные индексы — горячие пути запросов после M3
# ─────────────────────────────────────────────────────────────────────────────
COMPOSITE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_activity_stats_channel_username_date "
    "  ON activity_stats(channel_id, username, date(created_at))",
    "CREATE INDEX IF NOT EXISTS idx_chat_stats_channel_username_date "
    "  ON chat_stats(channel_id, username, date(created_at))",
    "CREATE INDEX IF NOT EXISTS idx_market_listings_channel_seller "
    "  ON market_listings(channel_id, seller)",
    "CREATE INDEX IF NOT EXISTS idx_marriages_channel_active "
    "  ON marriages(channel_id) WHERE divorced_at IS NULL",
    "CREATE INDEX IF NOT EXISTS idx_pending_duels_channel "
    "  ON pending_duels(channel_id)",
    "CREATE INDEX IF NOT EXISTS idx_drops_channel_username "
    "  ON drops(channel_id, username)",
    "CREATE INDEX IF NOT EXISTS idx_marriage_proposals_channel "
    "  ON marriage_proposals(channel_id)",
]

OLD_INDEXES_TO_DROP = [
    # Будут заменены композитными выше
    "idx_activity_stats_username_date",
    "idx_chat_stats_username_date",
]


# ─────────────────────────────────────────────────────────────────────────────
# Точка входа
# ─────────────────────────────────────────────────────────────────────────────

async def apply(conn) -> None:
    """Применить M1 миграцию идемпотентно."""
    chan_id = _default_channel_id()

    # Tracker
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS migrations_applied (
            name TEXT PRIMARY KEY,
            applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()

    # Phase 1: ADD COLUMN
    for table in ADD_COLUMN_TABLES:
        await _add_channel_id(conn, table, chan_id)

    # Phase 2: RECREATE
    for spec in RECREATE_TABLES:
        await _recreate_with_channel(conn, spec, chan_id)

    # Phase 3: purchase_counters special
    await _migrate_purchase_counters(conn, chan_id)

    # Phase 4: composite indexes
    await _apply_indexes(conn)

    print("✅ M1: multi-tenant schema migration complete")


async def _is_applied(conn, name: str) -> bool:
    cur = await conn.execute(
        "SELECT 1 FROM migrations_applied WHERE name = ?", (name,)
    )
    return await cur.fetchone() is not None


async def _mark_applied(conn, name: str) -> None:
    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,)
    )
    await conn.commit()


async def _table_exists(conn, table: str) -> bool:
    cur = await conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return await cur.fetchone() is not None


async def _column_exists(conn, table: str, column: str) -> bool:
    cur = await conn.execute(f"PRAGMA table_info({table})")
    cols = await cur.fetchall()
    return any(c[1] == column for c in cols)


async def _add_channel_id(conn, table: str, chan_id: int) -> None:
    """Идемпотентно добавляет channel_id колонку с DEFAULT-backfill."""
    name = f"M1.add_channel_id.{table}"
    if await _is_applied(conn, name):
        return
    if not await _table_exists(conn, table):
        # Не критично — таблица может появиться позже от другого migrations-блока
        print(f"⏭️  M1: пропуск {table} (таблица не существует)")
        await _mark_applied(conn, name)
        return
    if await _column_exists(conn, table, "channel_id"):
        # Колонка уже есть (ручная миграция / повтор)
        await _mark_applied(conn, name)
        return
    await conn.execute(
        f"ALTER TABLE {table} ADD COLUMN channel_id INTEGER NOT NULL DEFAULT {chan_id}"
    )
    await conn.commit()
    await _mark_applied(conn, name)
    print(f"✅ M1: channel_id → {table}")


async def _recreate_with_channel(conn, spec: dict, chan_id: int) -> None:
    """Пересоздаёт таблицу с новой схемой (включающей channel_id в PK/UNIQUE).

    Атомарно: rename old → create new → INSERT SELECT → drop old.
    Backfill: каждая старая строка получает channel_id = chan_id.
    """
    table = spec["table"]
    name = f"M1.recreate.{table}"

    if await _is_applied(conn, name):
        return

    if not await _table_exists(conn, table):
        if spec.get("skip_if_missing"):
            print(f"⏭️  M1: пропуск recreate {table} (таблица не существует)")
            await _mark_applied(conn, name)
            return
        # Таблица отсутствует, создаём с новой схемой сразу
        await conn.execute(f"CREATE TABLE {table} ({spec['new_schema']})")
        await conn.commit()
        await _mark_applied(conn, name)
        print(f"✅ M1: создана новая {table} (без миграции данных)")
        return

    # Если уже мигрирована руками (есть channel_id колонка в текущей схеме),
    # дополнительно проверим что PK/UNIQUE уже включает channel_id — если нет,
    # всё равно нужен пересоздать.
    cur = await conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    current_sql = ((await cur.fetchone()) or [""])[0] or ""
    has_channel_in_constraint = (
        "channel_id" in current_sql.lower()
        and ("primary key" in current_sql.lower() or "unique" in current_sql.lower())
        and "(channel_id" in current_sql.lower().replace(" ", "")
    )
    if has_channel_in_constraint:
        # Уже на новой схеме — отметить и выйти
        await _mark_applied(conn, name)
        return

    tmp = f"{table}__m1_old"
    copy_cols = spec["copy_cols_template"].format(chan=chan_id)

    await conn.execute("BEGIN IMMEDIATE")
    try:
        await conn.execute(f"ALTER TABLE {table} RENAME TO {tmp}")
        await conn.execute(f"CREATE TABLE {table} ({spec['new_schema']})")
        await conn.execute(f"INSERT INTO {table} SELECT {copy_cols} FROM {tmp}")
        await conn.execute(f"DROP TABLE {tmp}")
        await conn.commit()
    except Exception:
        await conn.execute("ROLLBACK")
        raise

    await _mark_applied(conn, name)
    print(f"✅ M1: recreated {table} (channel_id в PK/UNIQUE)")


async def _migrate_purchase_counters(conn, chan_id: int) -> None:
    """purchase_counters → rimworld_purchase_counters (pawn-scoped FK).

    Backfill: маппим (username) → pawn_id через rimworld_pawns. Записи без
    соответствующей пешки игнорируются (зритель ушёл, пешки нет — счётчик не
    нужен; новый раунд начнётся с базовой ценой).
    """
    name = "M1.purchase_counters_to_pawn_scoped"
    if await _is_applied(conn, name):
        return

    # Создаём новую таблицу
    await conn.execute(PURCHASE_COUNTERS_RECREATE)
    await conn.commit()

    # Если старой нет — мигрировать нечего
    if not await _table_exists(conn, "purchase_counters"):
        await _mark_applied(conn, name)
        print("✅ M1: rimworld_purchase_counters создана (старой purchase_counters не было)")
        return

    # Маппим username → pawn_id для текущего chan_id (single-tenant до M1).
    # rimworld_pawns уже имеет channel_id после Phase 2.
    await conn.execute("BEGIN IMMEDIATE")
    try:
        await conn.execute("""
            INSERT OR IGNORE INTO rimworld_purchase_counters (pawn_id, category, count)
            SELECT p.id, pc.category, pc.count
            FROM purchase_counters pc
            JOIN rimworld_pawns p
              ON p.username = pc.username AND p.channel_id = ?
        """, (chan_id,))
        # Старую таблицу убираем — больше не нужна
        await conn.execute("DROP TABLE purchase_counters")
        await conn.commit()
    except Exception:
        await conn.execute("ROLLBACK")
        raise

    await _mark_applied(conn, name)
    print("✅ M1: purchase_counters → rimworld_purchase_counters (pawn-scoped)")


async def _apply_indexes(conn) -> None:
    """Композитные индексы на горячих путях. Старые однотонные удаляются."""
    name = "M1.composite_indexes"
    if await _is_applied(conn, name):
        return

    for ddl in COMPOSITE_INDEXES:
        await conn.execute(ddl)
    for old in OLD_INDEXES_TO_DROP:
        await conn.execute(f"DROP INDEX IF EXISTS {old}")
    await conn.commit()
    await _mark_applied(conn, name)
    print(f"✅ M1: композитных индексов добавлено: {len(COMPOSITE_INDEXES)}")
