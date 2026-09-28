"""Regression: M109 repairs an existing unmarked table and stays idempotent."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent.absolute()
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))


async def main() -> int:
    import aiosqlite
    from migrations import m109_module_last_seen

    fd, path = tempfile.mkstemp(suffix=".db", prefix="test_m109_ledger_")
    os.close(fd)
    failures = []

    try:
        async with aiosqlite.connect(path) as conn:
            # Production had this exact state: schema exists, ledger marker does not.
            await conn.execute("""
                CREATE TABLE module_last_seen (
                    channel_id INTEGER NOT NULL,
                    module_id TEXT NOT NULL,
                    last_seen_ts REAL NOT NULL,
                    PRIMARY KEY (channel_id, module_id)
                )
            """)
            await conn.execute(
                "INSERT INTO module_last_seen VALUES (98319857, 'bannerlord', 1.0)"
            )
            await conn.commit()

            await m109_module_last_seen.apply(conn)
            await m109_module_last_seen.apply(conn)

            cur = await conn.execute(
                "SELECT COUNT(*) FROM migrations_applied "
                "WHERE name='M109.module_last_seen'"
            )
            if (await cur.fetchone())[0] != 1:
                failures.append("ledger marker must exist exactly once")

            cur = await conn.execute(
                "SELECT last_seen_ts FROM module_last_seen "
                "WHERE channel_id=98319857 AND module_id='bannerlord'"
            )
            row = await cur.fetchone()
            if row is None or row[0] != 1.0:
                failures.append("repair must preserve existing heartbeat data")

            cur = await conn.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='index' AND name='idx_module_last_seen_ch'"
            )
            if (await cur.fetchone())[0] != 1:
                failures.append("heartbeat lookup index must exist")
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
    print("ALL GREEN — M109 ledger repair is idempotent and preserves data.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
