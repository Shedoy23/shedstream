# -*- coding: utf-8 -*-
"""M106 — channel_id в дочерних таблицах пешек RimWorld.

M1 сделала tenant-aware таблицу ``rimworld_pawns``, но исторические дочерние
таблицы продолжили хранить только ``pawn_id``. Актуальный код фильтрует и
удаляет эти строки по двум ключам: ``channel_id`` и ``pawn_id``.

Миграция не удаляет данные:

* добавляет nullable-колонку старой таблице (ограничение SQLite ALTER TABLE);
* восстанавливает канал из родительской пешки;
* редкие orphan-строки без родителя относит к исходному broadcaster-каналу;
* добавляет индекс для горячих channel-scoped запросов.

На свежей БД колонка уже NOT NULL из database.py; тогда остаётся только
проверка/backfill и индекс. Идемпотентность — через migrations_applied.
"""
from __future__ import annotations

import os


_TABLES = (
    "rimworld_pawn_equipment",
    "rimworld_pawn_skills",
    "rimworld_pawn_hediffs",
    "rimworld_pawn_traits",
    "rimworld_pawn_genes",
)


async def _table_exists(conn, table: str) -> bool:
    cur = await conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return await cur.fetchone() is not None


async def _column_exists(conn, table: str, column: str) -> bool:
    cur = await conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in await cur.fetchall())


async def _is_applied(conn, name: str) -> bool:
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS migrations_applied "
        "(name TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cur = await conn.execute(
        "SELECT 1 FROM migrations_applied WHERE name = ?", (name,))
    return await cur.fetchone() is not None


def _default_channel_id() -> int:
    raw = os.getenv("TWITCH_BROADCASTER_ID", "0")
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


async def apply(conn) -> None:
    name = "M106.rimworld_pawn_children_scope"
    if await _is_applied(conn, name):
        return

    fallback_channel_id = _default_channel_id()
    migrated: list[str] = []

    await conn.execute("BEGIN IMMEDIATE")
    try:
        for table in _TABLES:
            if not await _table_exists(conn, table):
                continue

            if not await _column_exists(conn, table, "channel_id"):
                await conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN channel_id INTEGER")

            # Родитель — единственный авторитетный источник tenant-а.
            await conn.execute(
                f"UPDATE {table} "
                "SET channel_id = ("
                "  SELECT p.channel_id FROM rimworld_pawns p "
                f"  WHERE p.id = {table}.pawn_id"
                ") "
                "WHERE EXISTS ("
                "  SELECT 1 FROM rimworld_pawns p "
                f"  WHERE p.id = {table}.pawn_id "
                f"    AND ({table}.channel_id IS NULL "
                f"         OR {table}.channel_id <> p.channel_id)"
                ")"
            )

            # Legacy orphan-строки сохраняем, но не оставляем бесхозный tenant.
            await conn.execute(
                f"UPDATE {table} SET channel_id=? WHERE channel_id IS NULL",
                (fallback_channel_id,),
            )
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_channel_pawn "
                f"ON {table}(channel_id, pawn_id)"
            )
            migrated.append(table)

        await conn.execute(
            "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,))
        await conn.commit()
    except Exception:
        await conn.execute("ROLLBACK")
        raise

    print("✅ M106: дочерние таблицы пешек привязаны к channel_id "
          f"({len(migrated)} таблиц)")
