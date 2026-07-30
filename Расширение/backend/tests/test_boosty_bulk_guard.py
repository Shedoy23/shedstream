"""
test_boosty_bulk_guard.py — аудит спеки §17: массовая замена списка платных
подписчиков не должна стирать его «в пустоту».

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_boosty_bulk_guard.py

## Почему это единственное место, где так строго

Boosty — единственный список в проекте, стоящий рядом с НАСТОЯЩИМИ деньгами:
кто заплатил стримеру вне Twitch. Он ведётся руками, второго экземпляра нет,
восстановить его неоткуда.

## Дыра

`POST /api/dashboard/boosty/subscribers/bulk` с `replace_all: true` СНАЧАЛА
удаляет весь список канала, а негодные записи потом просто пропускает. Значит
файл, присланный целиком, но неверный по формату (все `tier` нулевые, поле
названо иначе, выгрузка из другой таблицы), оставлял стримера БЕЗ списка — и
ответ был `success`.

## Что требуем

    [1] replace_all + записи есть, но ни одной годной → отказ, список ЦЕЛ;
    [2] replace_all + годные записи → замена работает как раньше;
    [3] replace_all + пустой entries → список стирается (явная просьба);
    [4] частично годные записи → годные записаны, негодные посчитаны.

## Красный до фикса

    ❌ [1] список НЕ стёрт: expected 2, got 0
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import traceback
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

CHANNEL_ID = 98319857

_failures: list = []
_successes: list = []


def assert_eq(actual, expected, label: str):
    if actual == expected:
        _successes.append(label)
        print(f"  ✅ {label}")
    else:
        msg = f"  ❌ {label}: expected {expected!r}, got {actual!r}"
        _failures.append(msg)
        print(msg)


class _FakeRequest:
    """Только .json() — обработчик больше от запроса ничего не берёт
    (channel_id приходит из сессии, а её мы подменяем)."""

    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


async def _build_db(db_path: str):
    import main
    import dependencies
    from database import Database

    test_db = Database(db_path)
    main.db = test_db
    dependencies.set_db(test_db)
    await test_db.init_pool()
    await test_db.init_tables()
    await main.run_migrations()

    async with test_db._connect() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO channels (channel_id, login, display_name, tier) "
            "VALUES (?, 'chan', 'Chan', 'free')", (CHANNEL_ID,))
        await conn.commit()
    return test_db


async def _subs(db) -> list:
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT twitch_username, tier FROM bannerlord_boosty_subscribers "
            "WHERE channel_id=? ORDER BY twitch_username", (CHANNEL_ID,))
        return [(r[0], r[1]) for r in await cur.fetchall()]


async def _seed(db, rows):
    async with db._connect() as conn:
        await conn.execute(
            "DELETE FROM bannerlord_boosty_subscribers WHERE channel_id=?",
            (CHANNEL_ID,))
        for u, t in rows:
            await conn.execute(
                "INSERT INTO bannerlord_boosty_subscribers "
                "(channel_id, twitch_username, tier, note) VALUES (?, ?, ?, '')",
                (CHANNEL_ID, u, t))
        await conn.commit()


async def _run():
    db_path = tempfile.mktemp(suffix="_boosty_test.db")
    db = await _build_db(db_path)
    try:
        import routes.bannerlord_boosty as b
        b._require_dashboard_session = lambda request: CHANNEL_ID

        print("\n[1] Замена целиком негодными записями — отказ, список цел")
        await _seed(db, [("alice", 2), ("bob", 1)])
        res = await b.dashboard_bulk_set_boosty_subscribers(_FakeRequest({
            "replace_all": True,
            "entries": [
                {"username": "carol", "tier": 0},        # tier вне 1..3
                {"username": "", "tier": 2},             # нет ника
                {"user": "dave", "level": 3},            # поля названы иначе
            ],
        }))
        assert_eq(len(await _subs(db)), 2, "[1] список НЕ стёрт")
        assert_eq(res.get("success"), False, "[1] ответ — отказ, а не success")
        assert_eq(res.get("skipped"), 3, "[1] в ответе названо, сколько записей негодных")

        print("\n[2] Замена годными записями работает как раньше")
        res = await b.dashboard_bulk_set_boosty_subscribers(_FakeRequest({
            "replace_all": True,
            "entries": [{"username": "Erin", "tier": 3}],
        }))
        assert_eq(res.get("success"), True, "[2] замена прошла")
        assert_eq(await _subs(db), [("erin", 3)], "[2] список заменён на новый")

        print("\n[3] Явная просьба стереть (пустой список) — стираем")
        await _seed(db, [("alice", 2)])
        res = await b.dashboard_bulk_set_boosty_subscribers(_FakeRequest({
            "replace_all": True, "entries": [],
        }))
        assert_eq(res.get("success"), True, "[3] пустая замена принята")
        assert_eq(await _subs(db), [], "[3] список очищен по явной просьбе")

        print("\n[4] Часть записей негодная — годные проходят")
        await _seed(db, [("alice", 2)])
        res = await b.dashboard_bulk_set_boosty_subscribers(_FakeRequest({
            "replace_all": True,
            "entries": [{"username": "frank", "tier": 1},
                        {"username": "ghost", "tier": 9}],
        }))
        assert_eq(res.get("success"), True, "[4] частично годная замена принята")
        assert_eq(await _subs(db), [("frank", 1)], "[4] записан только годный")
    finally:
        try:
            await db._pool.close()
        except Exception:
            pass
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(db_path + suffix)
            except OSError:
                pass


def main():
    print("=" * 70)
    print("AUDIT_SPEC §17 — список платных подписчиков не стирается «в пустоту»")
    print("=" * 70)
    try:
        asyncio.run(_run())
    except Exception:
        print("\n💥 Test harness CRASHED (не assertion — инфраструктура):")
        traceback.print_exc()
        sys.exit(2)

    print("\n" + "=" * 70)
    print(f"PASSED: {len(_successes)}   FAILED: {len(_failures)}")
    if _failures:
        print("\nFAILURES:")
        for f in _failures:
            print(f)
        sys.exit(1)
    print("ALL GREEN ✅ — пустой результат не стирает список.")
    sys.exit(0)


if __name__ == "__main__":
    main()
