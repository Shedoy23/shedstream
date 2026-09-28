# -*- coding: utf-8 -*-
"""M97 — привязать RimWorld-таблицы к каналу.

ЗАЧЕМ. Четыре таблицы модуля живут без `channel_id` — наследие эпохи одного
стримера. Пока канал один, это невидимо. На втором рванёт сразу:

  * `shop_catalog` — заливка каталога делает `DELETE FROM shop_catalog` без
    условия, то есть стирает каталог ВСЕМ стримерам. Второй стример запустил
    игру — у первого магазин опустел.
  * `rimworld_event_catalog` — то же самое, `id` глобально уникален: событие с
    тем же идентификатором у другого стримера перезапишет чужое.
  * `purchase_counters` — ключ (username, category). Зритель с тем же ником на
    двух каналах делит счётчик прогрессивных цен: накупил генов у A — у B цены
    сразу высокие.
  * `rimworld_heal_cooldowns` — ключ (username). Полечился у A — кулдаун висит
    и у B.

Это ровно тот класс, ради которого сделан `check_tenant_scoping`, но
`rimworld.py` стоит в `tenant-lint: skip-file`, поэтому линтер сюда не смотрел.

КАК. SQLite не умеет менять PRIMARY KEY/UNIQUE у существующей таблицы, поэтому
пересоздаём: rename → create new → INSERT SELECT с backfill → drop old.
Backfill ставит всем строкам единственный существующий канал.

ВАЖНО (урок M1). M1 в июне пересоздала `purchase_counters` и удалила старую, но
код на новую не перевели, а `init_tables()` пересоздавал старую при каждом
старте — миграция «прошла», а по факту полтора месяца жила старая схема.
Поэтому здесь DDL правится И в миграции, И в местах, где таблицы создаются
лениво (`rimworld.py`), И запросы получают `channel_id`. Одно без другого —
повторение той же ловушки.

Идемпотентно через `migrations_applied`.
"""
import os


def _default_channel_id(conn=None) -> int:
    raw = (os.getenv("TWITCH_BROADCASTER_ID") or "").strip()
    if raw.isdigit():
        return int(raw)
    raise RuntimeError(
        "TWITCH_BROADCASTER_ID не задан или не число — M97 не может backfill'ить "
        "существующие строки каналом. Установи переменную.")


# (таблица, DDL новой схемы, список колонок для переноса)
SPECS = [
    (
        "shop_catalog",
        """
        CREATE TABLE shop_catalog (
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
        """,
        ["category", "def_name", "label", "description", "price",
         "base_price", "tech_level", "extra_json", "updated_at"],
    ),
    (
        "rimworld_event_catalog",
        """
        CREATE TABLE rimworld_event_catalog (
            channel_id INTEGER NOT NULL,
            id TEXT NOT NULL,
            name TEXT,
            cost INTEGER,
            cmd TEXT,
            params TEXT,
            category TEXT,
            PRIMARY KEY (channel_id, id)
        )
        """,
        ["id", "name", "cost", "cmd", "params", "category"],
    ),
    (
        "purchase_counters",
        """
        CREATE TABLE purchase_counters (
            channel_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            category TEXT NOT NULL,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (channel_id, username, category)
        )
        """,
        ["username", "category", "count"],
    ),
    (
        "rimworld_heal_cooldowns",
        """
        CREATE TABLE rimworld_heal_cooldowns (
            channel_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            last_heal_ts REAL NOT NULL,
            PRIMARY KEY (channel_id, username)
        )
        """,
        ["username", "last_heal_ts"],
    ),
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_shop_catalog_ch_cat "
    "ON shop_catalog(channel_id, category)",
    "CREATE INDEX IF NOT EXISTS idx_rw_event_catalog_ch_cat "
    "ON rimworld_event_catalog(channel_id, category)",
]


async def _is_applied(conn, name: str) -> bool:
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS migrations_applied "
        "(name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cur = await conn.execute(
        "SELECT 1 FROM migrations_applied WHERE name = ?", (name,))
    return await cur.fetchone() is not None


async def _mark_applied(conn, name: str) -> None:
    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,))


async def _table_exists(conn, table: str) -> bool:
    cur = await conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return await cur.fetchone() is not None


async def _has_column(conn, table: str, column: str) -> bool:
    cur = await conn.execute("PRAGMA table_info(%s)" % table)
    return any(r[1] == column for r in await cur.fetchall())


async def _recreate(conn, table: str, ddl: str, cols: list, chan_id: int) -> None:
    name = "M97.scope.%s" % table
    if await _is_applied(conn, name):
        return

    if not await _table_exists(conn, table):
        # Свежая база: таблицу ещё не создавали лениво — создаём сразу правильной.
        await conn.execute(ddl)
        await _mark_applied(conn, name)
        print("✅ M97: %s создана с channel_id (старой не было)" % table)
        return

    if await _has_column(conn, table, "channel_id"):
        await _mark_applied(conn, name)
        print("⏭️  M97: %s уже с channel_id" % table)
        return

    tmp = "%s_m97_old" % table
    await conn.execute("ALTER TABLE %s RENAME TO %s" % (table, tmp))
    await conn.execute(ddl)
    collist = ", ".join(cols)
    await conn.execute(
        "INSERT INTO %s (channel_id, %s) SELECT ?, %s FROM %s"
        % (table, collist, collist, tmp), (chan_id,))
    cur = await conn.execute("SELECT COUNT(*) FROM %s" % table)
    moved = (await cur.fetchone())[0]
    await conn.execute("DROP TABLE %s" % tmp)
    await _mark_applied(conn, name)
    print("✅ M97: %s привязана к каналу (перенесено строк: %d)" % (table, moved))


async def apply(conn) -> None:
    if await _is_applied(conn, "M97"):
        return
    chan_id = _default_channel_id(conn)

    # BEGIN IMMEDIATE на весь проход: half-migrated схема — худший исход,
    # часть таблиц с каналом, часть без, и код не знает какая где.
    await conn.execute("BEGIN IMMEDIATE")
    try:
        for table, ddl, cols in SPECS:
            await _recreate(conn, table, ddl, cols, chan_id)
        for ddl in INDEXES:
            await conn.execute(ddl)
        await _mark_applied(conn, "M97")
        await conn.commit()
    except Exception:
        await conn.execute("ROLLBACK")
        raise

    print("✅ M97: RimWorld-таблицы привязаны к каналу")
