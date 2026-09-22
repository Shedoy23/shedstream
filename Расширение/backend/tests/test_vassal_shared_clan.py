"""
test_vassal_shared_clan.py — REGRESSION: два зрителя в ОДНОМ клане.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_vassal_shared_clan.py

## Что за дыра

Вассалы принадлежат КЛАНУ, а не зрителю: мод собирает снимок через
`BuildSnapshotForMaster(hero.Clan)`, поэтому КАЖДЫЙ член клана шлёт один и тот
же список. Зеркало же хранит их с `parent_username`, а уникальный ключ —
`(channel_id, vassal_clan_id)`, то есть на канал.

Итог на проде 22.09: `@antitail` и `@ksiandil` оба в клане `[BLink] хвост`.
Строки вассалов закреплены за antitail. Снимок ksiandil пытался вставить те же
clan_id → `UNIQUE constraint failed: bannerlord_vassals.channel_id,
bannerlord_vassals.vassal_clan_id` → падала ВСЯ транзакция `player.state_update`,
а не только вассальная часть. У ksiandil замерло всё зеркало героя: в базе
уровень 20 и 882 587 динаров, в игре — уровень 24 и 9 585. Счёт отказов:
126 за 22.09 и 148 за 21.09, все по одному зрителю.

Класс — «одна запись — одно место»: два писателя одной строки.

## Чего требуем

1. Снимок второго члена клана НЕ роняет обработку — исключения нет.
2. Строка остаётся за первым владельцем: ping-pong между членами клана
   запрещён, иначе доход вассала будет прыгать между зрителями.
3. Своих вассалов зритель по-прежнему сверяет: пропавший из снимка уходит,
   новый появляется.

## Красный до фикса

    ❌ [1] снимок второго члена клана не роняет обработку: IntegrityError
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
OWNER = "antitail"     # первым завёл вассалов
MATE = "ksiandil"      # тот же клан, шлёт тот же список
SHARED = "[Vassal хвост] хвост1"

_failures: list = []
_successes: list = []


def check(ok: bool, label: str, detail: str = ""):
    if ok:
        _successes.append(label)
        print(f"  ✅ {label}")
    else:
        msg = f"  ❌ {label}{': ' + detail if detail else ''}"
        _failures.append(msg)
        print(msg)


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
            "VALUES (?, 'alice_chan', 'Alice Channel', 'free')", (CHANNEL_ID,))
        await conn.execute(
            "INSERT INTO bannerlord_vassals "
            "(channel_id,parent_username,vassal_clan_id,vassal_leader_hero_id,"
            " vassal_name,income_share_pct) VALUES (?,?,?,?,?,25.0)",
            (CHANNEL_ID, OWNER, SHARED, "hero_1", SHARED))
        await conn.commit()
    return test_db


def _snapshot(clan_id: str, leader: str = "hero_1"):
    return [{"clan_id": clan_id, "leader_hero_id": leader, "name": clan_id}]


async def test_mate_snapshot_does_not_explode(db):
    from routes.bannerlord_vassals import reconcile_vassal_snapshot
    crashed = ""
    async with db._connect() as conn:
        try:
            await reconcile_vassal_snapshot(conn, CHANNEL_ID, MATE, _snapshot(SHARED))
            await conn.commit()
        except Exception as ex:
            await conn.rollback()
            crashed = f"{type(ex).__name__}: {ex}"
    check(crashed == "", "[1] снимок второго члена клана не роняет обработку", crashed)


async def test_owner_keeps_the_row(db):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT parent_username FROM bannerlord_vassals "
            "WHERE channel_id=? AND vassal_clan_id=?", (CHANNEL_ID, SHARED))
        rows = await cur.fetchall()
    owners = [r[0] for r in rows]
    check(owners == [OWNER], "[2] вассал остался за первым владельцем",
          f"владельцы: {owners}")


async def test_own_vassals_still_reconciled(db):
    """Свой вассал у второго зрителя заводится и снимается как раньше."""
    from routes.bannerlord_vassals import reconcile_vassal_snapshot
    mine = "[Vassal хвост] личный"
    added = left = -1
    crashed = ""
    try:
        async with db._connect() as conn:
            await reconcile_vassal_snapshot(conn, CHANNEL_ID, MATE,
                                            _snapshot(SHARED) + _snapshot(mine, "hero_2"))
            await conn.commit()
            cur = await conn.execute(
                "SELECT COUNT(*) FROM bannerlord_vassals "
                "WHERE channel_id=? AND parent_username=?", (CHANNEL_ID, MATE))
            added = (await cur.fetchone())[0]
            await reconcile_vassal_snapshot(conn, CHANNEL_ID, MATE, _snapshot(SHARED))
            await conn.commit()
            cur = await conn.execute(
                "SELECT COUNT(*) FROM bannerlord_vassals "
                "WHERE channel_id=? AND parent_username=?", (CHANNEL_ID, MATE))
            left = (await cur.fetchone())[0]
    except Exception as ex:
        crashed = f"{type(ex).__name__}: {ex}"
    check(crashed == "" and added == 1 and left == 0,
          "[3] свой вассал заводится и снимается по снимку",
          crashed or f"после добавления {added}, после пропажи {left}")


async def main_async():
    tmp = tempfile.mkdtemp(prefix="vassal_shared_")
    db = await _build_db(os.path.join(tmp, "test.db"))
    try:
        await test_mate_snapshot_does_not_explode(db)
        await test_owner_keeps_the_row(db)
        await test_own_vassals_still_reconciled(db)
    finally:
        try:
            await db._pool.close()
        except Exception:
            pass

    print("\n" + "=" * 62)
    if _failures:
        print(f"ПРОВАЛЕНО: {len(_failures)}, пройдено: {len(_successes)}")
        for f in _failures:
            print(f)
        return 1
    print(f"ВСЁ ЗЕЛЁНОЕ: {len(_successes)} проверок")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main_async()))
    except Exception:
        traceback.print_exc()
        sys.exit(2)
