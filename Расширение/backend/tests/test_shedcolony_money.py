"""
test_shedcolony_money.py — money/compliance invariants for the ShedColony viewer layer.

Standalone (no pytest). Run from backend/:
    python tests/test_shedcolony_money.py

Exercises routes/shedcolony._buy_action_locked + ShedColonyAdapter._on_action_failed
DIRECTLY (no JWT, no live game) against a synthetic channel, then cleans up. Covers:
  1. spawn charges exactly the server-side price (points decrement)
  2. enqueued action carries price + initiated_by (the refund hook depends on it)
  3. idempotency — same client_action_id never double-charges
  4. refund-on-failure — action.failed restores the exact price (Twitch compliance)
  5. refund idempotency — never double-refunds
  6. spawn-guard — refuses a second spawn while a colonist is alive (1 viewer = 1 colonist)
  7. insufficient funds — refuses and does not charge

A failure here is a real regression in a MONEY/compliance invariant.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

HERE = Path(__file__).parent.absolute()
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("TWITCH_OAUTH_TOKEN", "oauth:test")
os.environ.setdefault("TWITCH_CLIENT_ID", "test_client")
os.environ.setdefault("TWITCH_CLIENT_SECRET", "test_secret")
os.environ.setdefault("TWITCH_BOT_ID", "test_bot")
os.environ.setdefault("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab")
os.environ.setdefault("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890")
os.environ.setdefault("ADMIN_PASSWORD", "test_admin_password_for_tests_only")
os.environ.setdefault("TWITCH_BROADCASTER_ID", "98319857")
os.environ.setdefault("TWITCH_CHANNEL_NAME", "test_channel")

_temp = tempfile.NamedTemporaryFile(prefix="shedlink-money-", suffix=".db", delete=False)
_temp.close()
_TEST_DB_PATH = Path(_temp.name)
os.environ["DB_PATH"] = str(_TEST_DB_PATH)

from database import Database                              # noqa: E402
from dependencies import set_db, get_db                    # noqa: E402
import routes.shedcolony as sc                             # noqa: E402
from modules._base import ModuleEnvelope                   # noqa: E402
from modules.shedcolony._adapter import ShedColonyAdapter  # noqa: E402
import main as main_mod                                    # noqa: E402

CH = 990099                       # synthetic channel — invisible to the live mod
USER = "sc_money_test_user"

_fails: list[str] = []


def check(name: str, cond: bool) -> None:
    print(("  PASS " if cond else "  FAIL ") + name)
    if not cond:
        _fails.append(name)


async def _points() -> int | None:
    async with get_db()._connect() as conn:
        cur = await conn.execute(
            "SELECT points FROM viewers WHERE channel_id=? AND username=?", (CH, USER))
        r = await cur.fetchone()
    return r[0] if r else None


async def _seed_points(p: int) -> None:
    async with get_db()._connect() as conn:
        await conn.execute("DELETE FROM viewers WHERE channel_id=? AND username=?", (CH, USER))
        await conn.execute(
            "INSERT INTO viewers (channel_id, username, points, last_seen, join_time, is_afk) "
            "VALUES (?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,0)", (CH, USER, p))


async def _cleanup() -> None:
    async with get_db()._connect() as conn:
        await conn.execute("DELETE FROM viewers WHERE channel_id=?", (CH,))
        await conn.execute("DELETE FROM module_actions WHERE channel_id=?", (CH,))
        await conn.execute("DELETE FROM shedcolony_colony_link WHERE channel_id=?", (CH,))


async def main() -> None:
    db = Database(str(_TEST_DB_PATH))
    await db.init_pool()
    await db.init_tables()
    await main_mod.run_migrations()
    set_db(db)
    adapter = ShedColonyAdapter.__new__(ShedColonyAdapter)   # _on_action_failed uses only get_db
    try:
        await _cleanup()

        # ── 1+2) charge + enqueued payload ──
        await _seed_points(5000)
        r1 = await sc._buy_action_locked(USER, CH, "colonist.spawn", {"client_action_id": "cid_A"})
        check("spawn returns success", bool(r1.get("success")))
        check("spawn charged exactly 1000", r1.get("charged") == 1000)
        check("points decremented 5000→4000", (await _points()) == 4000)
        async with get_db()._connect() as conn:
            cur = await conn.execute(
                "SELECT action_id, type, status, data FROM module_actions "
                "WHERE channel_id=? AND client_action_id='cid_A'", (CH,))
            row = await cur.fetchone()
        check("action enqueued (queued/colonist.spawn)",
              row is not None and row[2] == "queued" and row[1] == "colonist.spawn")
        action_id = row[0]
        payload = json.loads(row[3])
        check("payload carries price=1000 + initiated_by (refund depends on it)",
              payload.get("price") == 1000 and payload.get("initiated_by") == USER)

        # ── 3) idempotency: same client_action_id never double-charges ──
        r2 = await sc._buy_action_locked(USER, CH, "colonist.spawn", {"client_action_id": "cid_A"})
        check("idempotent replay returned", bool(r2.get("idempotent_replay")))
        check("no double-charge (still 4000)", (await _points()) == 4000)

        # ── 4) refund-on-failure restores the exact price ──
        env = ModuleEnvelope(id="m1", kind="event", type="action.failed", ts=0,
                             data={"action_id": action_id, "reason": "op_failed"})
        await adapter._on_action_failed(CH, env)
        check("refund restored 4000→5000", (await _points()) == 5000)
        async with get_db()._connect() as conn:
            cur = await conn.execute(
                "SELECT status, error_msg FROM module_actions WHERE channel_id=? AND action_id=?",
                (CH, action_id))
            st = await cur.fetchone()
        check("action marked failed + REFUNDED",
              st[0] == "failed" and (st[1] or "").startswith("REFUNDED:"))

        # ── 5) refund idempotency: never double-refunds ──
        await adapter._on_action_failed(CH, env)
        check("no double-refund (still 5000)", (await _points()) == 5000)

        # ── 6) spawn-guard: refuse a second spawn while a colonist is alive ──
        async with get_db()._connect() as conn:
            await conn.execute(
                "INSERT INTO shedcolony_colony_link "
                "(channel_id, viewer_id, citizen_id, colony_id, status) VALUES (?,?,?,?, 'active')",
                (CH, USER, "777", "1"))
        rg = await sc._buy_action_locked(USER, CH, "colonist.spawn", {"client_action_id": "cid_B"})
        check("second spawn refused (already has colonist)", rg.get("success") is False)
        check("guard did not charge (still 5000)", (await _points()) == 5000)
        async with get_db()._connect() as conn:
            await conn.execute("DELETE FROM shedcolony_colony_link WHERE channel_id=?", (CH,))

        # ── 7) insufficient funds: refuse + do not charge ──
        await _seed_points(50)
        ri = await sc._buy_action_locked(USER, CH, "colonist.spawn", {"client_action_id": "cid_C"})
        check("insufficient funds refused",
              ri.get("success") is False and "крустик" in (ri.get("message") or "").lower())
        check("insufficient did not charge (still 50)", (await _points()) == 50)
    finally:
        await _cleanup()
        # 2026-07-30: без этого процесс НЕ ЗАВЕРШАЛСЯ. Проверки печатали
        # «OK — all ... invariants hold», а прогон висел до ручного убийства:
        # DBPool держит фоновые соединения, и `asyncio.run` не может закрыть
        # цикл, пока они живы. Читающий вывод видел «OK» и уходил довольным —
        # худшая форма класса «зелёная печать ≠ зелёный результат» (CLAUDE.md
        # §4), потому что кода возврата не наступало вообще.
        await db._pool.close()
        _TEST_DB_PATH.unlink(missing_ok=True)

    print()
    if _fails:
        print(f"FAILED ({len(_fails)}): {_fails}")
        sys.exit(1)
    print("OK — all ShedColony money/compliance invariants hold")


asyncio.run(main())
