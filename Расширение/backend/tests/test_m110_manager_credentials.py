"""Regression for the M110 Manager credential ledger schema."""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent.absolute()
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))


async def main() -> int:
    import aiosqlite
    from migrations import m110_manager_credentials

    fd, path = tempfile.mkstemp(suffix=".db", prefix="test_m110_manager_")
    os.close(fd)
    failures = []
    try:
        async with aiosqlite.connect(path) as conn:
            await conn.execute("PRAGMA foreign_keys=ON")
            await m110_manager_credentials.apply(conn)
            await m110_manager_credentials.apply(conn)

            expected = {"manager_pairings", "manager_sessions", "module_credentials"}
            cur = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in await cur.fetchall()}
            if not expected.issubset(tables):
                failures.append("missing Manager ledger tables")

            cur = await conn.execute(
                "SELECT COUNT(*) FROM migrations_applied "
                "WHERE name='M110.manager_credentials'"
            )
            if (await cur.fetchone())[0] != 1:
                failures.append("M110 marker must exist exactly once")

            await conn.execute(
                "INSERT INTO manager_pairings "
                "(id,device_challenge,user_code_hash,installation_id_hash,module_id,created_at,expires_at) "
                "VALUES ('p1','challenge','code-hash','install-hash','rimworld',1,2)"
            )
            try:
                await conn.execute(
                    "INSERT INTO manager_pairings "
                    "(id,device_challenge,user_code_hash,installation_id_hash,module_id,created_at,expires_at) "
                    "VALUES ('p2','other','code-hash','other-install','rimworld',1,2)"
                )
                failures.append("duplicate user-code hash was accepted")
            except sqlite3.IntegrityError:
                pass

            try:
                await conn.execute("UPDATE manager_pairings SET status='unknown' WHERE id='p1'")
                failures.append("invalid pairing status was accepted")
            except sqlite3.IntegrityError:
                pass

            await conn.execute(
                "INSERT INTO module_credentials "
                "(id,channel_id,module_id,secret_hash,label,created_at,expires_at) "
                "VALUES ('c1',11,'rimworld','secret-1','PC 1',1,2)"
            )
            await conn.execute(
                "INSERT INTO module_credentials "
                "(id,channel_id,module_id,secret_hash,label,created_at,expires_at) "
                "VALUES ('c2',22,'rimworld','secret-2','PC 2',1,2)"
            )
            await conn.commit()

            cur = await conn.execute(
                "SELECT channel_id,module_id FROM module_credentials ORDER BY channel_id"
            )
            scopes = await cur.fetchall()
            if scopes != [(11, "rimworld"), (22, "rimworld")]:
                failures.append("credential scope was not preserved per channel")
    finally:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(path + suffix)
            except OSError:
                pass

    if failures:
        for failure in failures:
            print("FAIL: " + failure)
        return 1
    print("ALL GREEN — M110 ledger is strict, scoped and idempotent.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
