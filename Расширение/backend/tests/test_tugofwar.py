"""
test_tugofwar.py — «Канат» 1×1: рейтинг, сезон, ноль случайности.

Standalone (без pytest). Запуск из backend/:
    python tests/test_tugofwar.py

ЗАЧЕМ. Канат заменил кубики (решение владельца 2026-09-01) и устроен ПО ПРИНЦИПУ
остальных игр: очередь подбора, комната на двоих, ELO, сезон, призы топ-3.
Командный вариант, написанный в тот же день, убран по решению владельца.

Почему 1×1 важен не только для интереса: в командном варианте комплаенс-ревью
запретило вешать крустики на исход — «выбрал сторону → исход зависит не от тебя →
получил валюту» читается как ставка. В дуэли исход целиком в руках двоих,
поэтому сезонный приз стоит на той же почве, что у крестиков и дуэлей.

Тест держит:

1. **За матч крустики не платятся.** Платит только сезон — как в крестиках.
2. **Рейтинг двигается в правильную сторону** и сумма ELO сохраняется.
3. **Ничья остаётся ничьёй** — победитель не разыгрывается.
4. **Затухание и детерминизм**: тот же вход даёт тот же результат, тап не падает
   ниже пола, канат — отношение, а не разность.
5. **Сезон платит топ-3 и только выше порога ELO**, и платит РОВНО ОДИН РАЗ.
6. **Каналы изолированы.**
7. **В модуле нет ни одного обращения к случайности.**
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta
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
OTHER_CHANNEL = 12345678

_failures: list = []


def assert_eq(actual, expected, label: str):
    if actual == expected:
        print(f"  OK  {label}")
    else:
        msg = f"  FAIL {label}: expected {expected!r}, got {actual!r}"
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
        for cid, login in ((CHANNEL_ID, "alice_chan"), (OTHER_CHANNEL, "bob_chan")):
            await conn.execute(
                "INSERT OR IGNORE INTO channels (channel_id, login, display_name, tier) "
                "VALUES (?, ?, ?, 'free')", (cid, login, login))
            for who in ("alice", "bob"):
                await conn.execute(
                    "INSERT INTO viewers (channel_id, username, points) VALUES (?, ?, 0)",
                    (cid, who))
        await conn.commit()
    return test_db


async def _points(db, channel_id, username):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT points FROM viewers WHERE channel_id=? AND username=?",
            (channel_id, username))
        row = await cur.fetchone()
    return row[0] if row else None


async def _elo(db, channel_id, username, tug):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT elo FROM duel_stats WHERE channel_id=? AND username=? AND game_type=?",
            (channel_id, username, tug.GAME_TYPE))
        row = await cur.fetchone()
    return row[0] if row else None


async def _make_room(db, tug, room_id: str, channel_id=CHANNEL_ID,
                     a="alice", b="bob", elo_a=1000, elo_b=1000):
    """Комната, какой её создаёт общий подбор. Состояние пустое — модуль сам
    инициализирует его при первом чтении, как в проде."""
    async with db._connect() as conn:
        await conn.execute(
            "INSERT INTO match_rooms (room_id, channel_id, game_type, player_a, player_b, "
            " player_a_elo, player_b_elo, state, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, '{}', 'active')",
            (room_id, channel_id, tug.GAME_TYPE, a, b, elo_a, elo_b))
        await conn.commit()


async def _expire_match(db, room_id):
    async with db._connect() as conn:
        cur = await conn.execute("SELECT state FROM match_rooms WHERE room_id=?", (room_id,))
        state = json.loads((await cur.fetchone())[0])
        state["ends_at"] = time.time() - 1
        state["last"] = {"a": 0.0, "b": 0.0}
        await conn.execute("UPDATE match_rooms SET state=? WHERE room_id=?",
                           (json.dumps(state), room_id))
        await conn.commit()


async def _reset_cooldown(db, room_id):
    async with db._connect() as conn:
        cur = await conn.execute("SELECT state FROM match_rooms WHERE room_id=?", (room_id,))
        state = json.loads((await cur.fetchone())[0])
        state["last"] = {"a": 0.0, "b": 0.0}
        await conn.execute("UPDATE match_rooms SET state=? WHERE room_id=?",
                           (json.dumps(state), room_id))
        await conn.commit()


async def test_match_pays_nothing_but_moves_elo(db, tug):
    print("\n[1] За матч крустики не платятся, рейтинг двигается")
    await _make_room(db, tug, "room-1")
    await tug.status_for("alice", CHANNEL_ID)          # инициализация состояния
    for _ in range(3):
        await tug.pull_rope("alice", CHANNEL_ID, 10)
        await _reset_cooldown(db, "room-1")
    await tug.pull_rope("bob", CHANNEL_ID, 3)
    await _expire_match(db, "room-1")
    res = await tug.status_for("alice", CHANNEL_ID)

    assert_eq(res["room"]["outcome"], "win_a", "победил тот, кто натянул сильнее")
    assert_eq(await _points(db, CHANNEL_ID, "alice"), 0,
              "победителю за МАТЧ крустики не начислены")
    assert_eq(await _points(db, CHANNEL_ID, "bob"), 0, "проигравшему тоже ноль")
    assert_eq(res["rules"]["match_reward"], 0,
              "в правилах прямо сказано: за матч не платят")

    elo_a = await _elo(db, CHANNEL_ID, "alice", tug)
    elo_b = await _elo(db, CHANNEL_ID, "bob", tug)
    assert_eq(elo_a > 1000, True, "рейтинг победителя вырос")
    assert_eq(elo_b < 1000, True, "рейтинг проигравшего упал")
    assert_eq(elo_a + elo_b, 2000, "сумма рейтингов сохранилась")


async def test_draw_stays_draw(db, tug):
    print("\n[2] Ничья остаётся ничьёй, монетку не бросаем")
    await _make_room(db, tug, "room-2", a="alice", b="bob", elo_a=1200, elo_b=1200)
    await tug.status_for("alice", CHANNEL_ID)
    await tug.pull_rope("alice", CHANNEL_ID, 7)
    await tug.pull_rope("bob", CHANNEL_ID, 7)
    await _expire_match(db, "room-2")
    res = await tug.status_for("bob", CHANNEL_ID)
    assert_eq(res["room"]["outcome"], "draw", "равный вклад — ничья")
    async with db._connect() as conn:
        cur = await conn.execute("SELECT winner FROM match_rooms WHERE room_id='room-2'")
        assert_eq((await cur.fetchone())[0], None, "победитель не назначен")


async def test_decay_and_determinism(tug):
    print("\n[3] Затухание, пол и детерминизм")
    ten = tug._batch_value(0, 10)
    assert_eq(ten < tug.TAP_BASE * 10, True, "десять тапов дешевле десяти базовых")
    assert_eq(tug._batch_value(0, 10), ten, "тот же вход — тот же результат")
    assert_eq(tug._tap_value(10_000), tug.TAP_MIN, "цена тапа не ниже пола")
    assert_eq(tug._rope_pos(500, 500), 0, "равный вклад — канат посередине")
    assert_eq(tug._rope_pos(1000, 0), tug.ROPE_LIMIT, "односторонняя тяга — край")
    assert_eq(tug._rope_pos(2000, 1000), tug._rope_pos(200, 100),
              "позиция — отношение, а не разность")


async def test_season_pays_top_and_only_once(db, tug):
    print("\n[4] Сезон платит топ-3 выше порога и ровно один раз")
    async with db._connect() as conn:
        season_id = await tug._ensure_season(conn, CHANNEL_ID)
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        await conn.execute("UPDATE duel_seasons SET ends_at=? WHERE id=?", (past, season_id))
        # alice выше порога, bob — ниже: он не должен получить ничего.
        await conn.execute(
            "INSERT OR REPLACE INTO duel_stats "
            "(channel_id, username, game_type, elo, win_streak, season_id) "
            "VALUES (?, 'alice', ?, ?, 0, ?)",
            (CHANNEL_ID, tug.GAME_TYPE, tug.PRIZE_ELO_GATE + 50, season_id))
        await conn.execute(
            "INSERT OR REPLACE INTO duel_stats "
            "(channel_id, username, game_type, elo, win_streak, season_id) "
            "VALUES (?, 'bob', ?, ?, 0, ?)",
            (CHANNEL_ID, tug.GAME_TYPE, tug.PRIZE_ELO_GATE - 50, season_id))
        await conn.commit()

    before_a = await _points(db, CHANNEL_ID, "alice")
    before_b = await _points(db, CHANNEL_ID, "bob")
    await tug.check_season_end(CHANNEL_ID)
    assert_eq(await _points(db, CHANNEL_ID, "alice") - before_a, tug.PRIZES[1],
              "первое место получило приз")
    assert_eq(await _points(db, CHANNEL_ID, "bob") - before_b, 0,
              "рейтинг ниже порога — приза нет")

    after = await _points(db, CHANNEL_ID, "alice")
    await tug.check_season_end(CHANNEL_ID)
    await tug.check_season_end(CHANNEL_ID)
    assert_eq(await _points(db, CHANNEL_ID, "alice"), after,
              "повторные проходы не платят второй раз")


async def test_channel_isolation(db, tug):
    print("\n[5] Каналы изолированы")
    await _make_room(db, tug, "room-3", channel_id=OTHER_CHANNEL)
    mine = await tug.status_for("alice", CHANNEL_ID)
    other = await tug.status_for("alice", OTHER_CHANNEL)
    assert_eq(other["room"]["room_id"], "room-3", "свой канал видит свою комнату")
    assert_eq(mine["room"]["room_id"] if mine["room"] else None, "room-2",
              "чужая комната в свой канал не протекла")


def test_no_randomness(tug):
    print("\n[6] В модуле нет обращений к случайности")
    src = Path(tug.__file__).read_text(encoding="utf-8")
    code = " ".join(line.split("#", 1)[0] for line in src.splitlines())
    assert_eq("import random" not in code, True, "модуль не импортирует random")
    for call in ("random.", "randint(", "choice(", "shuffle(", "sample("):
        assert_eq(call not in code, True, f"нет вызова {call}")


async def _run():
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_tug_")
    os.close(fd)
    db = await _build_db(db_path)
    from routes import tugofwar as tug
    try:
        await test_match_pays_nothing_but_moves_elo(db, tug)
        await test_draw_stays_draw(db, tug)
        await test_decay_and_determinism(tug)
        await test_season_pays_top_and_only_once(db, tug)
        await test_channel_isolation(db, tug)
        test_no_randomness(tug)
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

    print("\n" + "=" * 70)
    if _failures:
        print(f"ПРОВАЛ: {len(_failures)}")
        for f in _failures:
            print(f)
        return 1
    print("ВСЁ ЗЕЛЁНОЕ — матч без выплат, сезон платит топ-3, случайности нет")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
