# -*- coding: utf-8 -*-
"""M106 preserves legacy pawn details and assigns the parent's channel."""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import tempfile

import aiosqlite

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("TWITCH_BROADCASTER_ID", "98319857")

CHANNEL_A = 98319857
CHANNEL_B = 12345678
TABLES = (
    "rimworld_pawn_equipment",
    "rimworld_pawn_skills",
    "rimworld_pawn_hediffs",
    "rimworld_pawn_traits",
    "rimworld_pawn_genes",
)


async def main() -> int:
    db_path = tempfile.mktemp(suffix="_rw_m106.db")
    try:
        async with aiosqlite.connect(db_path) as conn:
            await conn.execute("""
                CREATE TABLE rimworld_pawns (
                    id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    pawn_name TEXT NOT NULL
                )
            """)
            await conn.executemany(
                "INSERT INTO rimworld_pawns "
                "(id, channel_id, username, pawn_name) VALUES (?, ?, ?, ?)",
                (
                    (1, CHANNEL_A, "same_viewer", "Pawn A"),
                    (2, CHANNEL_B, "same_viewer", "Pawn B"),
                ),
            )
            for table in TABLES:
                await conn.execute(
                    f"CREATE TABLE {table} "
                    "(id INTEGER PRIMARY KEY, pawn_id INTEGER NOT NULL, value TEXT)")
                await conn.executemany(
                    f"INSERT INTO {table} (id, pawn_id, value) VALUES (?, ?, ?)",
                    ((1, 1, "A"), (2, 2, "B")),
                )
            await conn.commit()

            from migrations import m106_rimworld_pawn_children_scope as m106
            await m106.apply(conn)
            # Идемпотентность: второй запуск ничего не меняет и не падает.
            await m106.apply(conn)

            failures: list[str] = []
            for table in TABLES:
                cur = await conn.execute(
                    f"SELECT channel_id, pawn_id, value FROM {table} ORDER BY id")
                rows = await cur.fetchall()
                expected = [
                    (CHANNEL_A, 1, "A"),
                    (CHANNEL_B, 2, "B"),
                ]
                if rows != expected:
                    failures.append(f"{table}: {rows!r}")

                cur = await conn.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type='index' AND name=?",
                    (f"idx_{table}_channel_pawn",),
                )
                if await cur.fetchone() is None:
                    failures.append(f"{table}: missing index")

            if failures:
                print("FAILED:")
                for failure in failures:
                    print("  " + failure)
                return 1
            print(f"ALL GREEN — M106 сохранила и изолировала {len(TABLES)} таблиц")
            return 0
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(db_path + suffix)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
