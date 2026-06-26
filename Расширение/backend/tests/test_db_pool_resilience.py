"""
test_db_pool_resilience.py — DBPool must not hang/crash on a transient DB failure.

Standalone (no pytest). Run from backend/:
    python tests/test_db_pool_resilience.py

Regression for the 2026-06-25 prod outages: a restart hit a briefly-unavailable DB,
the pool opened 0 connections, and acquire() blocked 30s on an empty queue →
TimeoutError → the bootstrap crashed. The pool must instead retry (transient
recovery) and fast-fail (clear error, no long hang) when the DB is truly unopenable.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))

from db_pool import DBPool  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool) -> None:
    print(("  PASS " if cond else "  FAIL ") + name)
    if not cond:
        _fails.append(name)


async def main() -> None:
    # A — a healthy DB: normal acquire / release / query works.
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    pool = DBPool(path, min_size=2, max_size=5, timeout=5.0)
    await pool.initialize()
    conn = await pool.acquire()
    cur = await conn.execute("SELECT 1")
    row = await cur.fetchone()
    check("healthy pool: acquire + SELECT 1 works", bool(row) and row[0] == 1)
    await pool.release(conn)
    await pool.close()
    os.remove(path)

    # B — an unopenable DB (path is a directory): acquire must FAST-FAIL, not hang 30s.
    d = tempfile.mkdtemp()
    pool2 = DBPool(d, min_size=1, max_size=5, timeout=1.0)
    await pool2.initialize()                       # expected: 0 connections after retries
    t0 = time.time()
    raised = False
    try:
        await pool2.acquire(timeout=30.0)
    except Exception:
        raised = True
    elapsed = time.time() - t0
    check("unopenable DB: acquire raises (does not hang)", raised)
    check(f"unopenable DB: fails fast (~{elapsed:.1f}s, not 30s)", elapsed < 15)
    try:
        os.rmdir(d)
    except OSError:
        pass

    print()
    if _fails:
        print(f"FAILED ({len(_fails)}): {_fails}")
        sys.exit(1)
    print("OK — DBPool retries transient failures and fast-fails instead of hanging/crashing")


asyncio.run(main())
