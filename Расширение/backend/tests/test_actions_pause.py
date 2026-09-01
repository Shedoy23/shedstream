"""
test_actions_pause.py — аварийная остановка стримера действительно останавливает.

Standalone (без pytest). Запуск из backend/:
    python tests/test_actions_pause.py

ЗАЧЕМ. 2026-09-01: у стримера не было НИ ОДНОГО способа прекратить воздействия
зрителей на игру, кроме рестарта бэкенда. Пока стример один и сервер его
собственный — терпимо; для чужого человека в эфире это дыра.

Затворов два, и оба обязательны:

  * **касса** — платное действие отклоняется ДО списания. Закрыть только выдачу
    заданий значило бы продолжать брать деньги за то, что не произойдёт;
  * **выдача заданий моду** — пока пауза взведена, мод не получает ничего,
    включая задания, поставленные ДО нажатия кнопки. Закрыть только кассу
    значило бы выпустить в игру всё, что уже стоит в очереди.

Тест держит четыре границы:

1. Пауза отклоняет покупку, деньги не списаны, задание не поставлено, и отказ
   НАЗЫВАЕТ причину (зритель должен понять, что это не поломка).
2. Снятая пауза не мешает: тот же вызов уже не отклоняется паузой.
3. Пауза одного канала не глушит другой — иначе первый же чужой стример
   выключит эфир владельцу.
4. Мод не получает даже то, что стояло в очереди ДО паузы.

Почему пункт 2 проверяет «не отклонено ПАУЗОЙ», а не «покупка прошла»: у
действия свои игровые гейты (жив ли герой, хватает ли динаров), и завязывать
проверку затвора на их выполнение значит получить тест, который позеленеет или
покраснеет по чужой причине.
"""
from __future__ import annotations

import asyncio
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

CHANNEL_ID = 98319857
OTHER_CHANNEL_ID = 12345678
START_POINTS = 100_000

_failures: list = []


def assert_eq(actual, expected, label: str):
    if actual == expected:
        print(f"  OK  {label}")
    else:
        msg = f"  FAIL {label}: expected {expected!r}, got {actual!r}"
        _failures.append(msg)
        print(msg)


def _make_anon_request():
    from starlette.requests import Request
    return Request({"type": "http", "method": "POST",
                    "path": "/api/bannerlord/action",
                    "headers": [], "query_string": b""})


async def _points(db, channel_id, username):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT points FROM viewers WHERE channel_id=? AND username=?",
            (channel_id, username))
        row = await cur.fetchone()
    return row[0] if row else None


async def _count_actions(db, channel_id):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM module_actions WHERE channel_id=?", (channel_id,))
        return (await cur.fetchone())[0]


async def _set_pause(db, channel_id, paused):
    from actions_pause import set_paused
    async with db._connect() as conn:
        await set_paused(conn, channel_id, paused)
        await conn.commit()


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
        for cid, login in ((CHANNEL_ID, "alice_chan"), (OTHER_CHANNEL_ID, "bob_chan")):
            await conn.execute(
                "INSERT OR IGNORE INTO channels (channel_id, login, display_name, tier) "
                "VALUES (?, ?, ?, 'free')", (cid, login, login))
            await conn.execute(
                "INSERT INTO viewers (channel_id, username, points) VALUES (?, 'alice', ?)",
                (cid, START_POINTS))
            await conn.execute(
                "INSERT INTO bannerlord_heroes "
                "(channel_id, username, hero_id, display_name, is_alive, gold) "
                "VALUES (?, 'alice', ?, 'Alice', 1, 500000)",
                (cid, f"hero_alice_{cid}"))
        await conn.commit()
    return test_db


ACTION = "hero.add_attribute"
PAYLOAD = {"skill_key": "Vigor", "client_action_id": "pause-test-1"}


async def test_pause_refuses_before_charge(db, buy):
    print("\n[1] Пауза: покупка отклонена, деньги целы, очередь не выросла")
    await _set_pause(db, CHANNEL_ID, True)
    before = await _points(db, CHANNEL_ID, "alice")
    queued_before = await _count_actions(db, CHANNEL_ID)

    res = await buy(_make_anon_request(), "alice", CHANNEL_ID, ACTION, dict(PAYLOAD))

    assert_eq(res.get("success"), False, "покупка отклонена")
    assert_eq(res.get("paused"), True, "отказ помечен как пауза")
    assert_eq("пауз" in (res.get("message") or "").lower(), True,
              "отказ НАЗЫВАЕТ причину зрителю")
    assert_eq(await _points(db, CHANNEL_ID, "alice"), before, "крустики не списаны")
    assert_eq(await _count_actions(db, CHANNEL_ID), queued_before,
              "задание не поставлено в очередь")


async def test_unpaused_not_blocked(db, buy):
    print("\n[2] Пауза снята: затвор больше не отклоняет")
    await _set_pause(db, CHANNEL_ID, False)
    res = await buy(_make_anon_request(), "alice", CHANNEL_ID, ACTION,
                    dict(PAYLOAD, client_action_id="pause-test-2"))
    assert_eq(res.get("paused"), None, "отказа по паузе больше нет")


async def test_pause_is_per_channel(db, buy):
    print("\n[3] Пауза одного канала не глушит другой")
    await _set_pause(db, CHANNEL_ID, True)
    await _set_pause(db, OTHER_CHANNEL_ID, False)
    res_other = await buy(_make_anon_request(), "alice", OTHER_CHANNEL_ID, ACTION,
                          dict(PAYLOAD, client_action_id="pause-test-3"))
    assert_eq(res_other.get("paused"), None, "соседний канал работает")

    res_mine = await buy(_make_anon_request(), "alice", CHANNEL_ID, ACTION,
                         dict(PAYLOAD, client_action_id="pause-test-4"))
    assert_eq(res_mine.get("paused"), True, "свой канал по-прежнему на паузе")


async def test_queue_not_handed_to_mod(db):
    print("\n[4] Мод не получает даже то, что стояло в очереди ДО паузы")
    from actions_pause import pending_actions_unless_paused
    await _set_pause(db, CHANNEL_ID, False)
    async with db._connect() as conn:
        await conn.execute(
            "INSERT INTO module_actions "
            "(channel_id, module_id, action_id, type, data, status) "
            "VALUES (?, 'bannerlord', 'act-before-pause', 'hero.heal', '{}', 'queued')",
            (CHANNEL_ID,))
        await conn.commit()

    # Порядок важен: выдача заданий помечает их `dispatched`, то есть ЗАБИРАЕТ
    # из очереди. Первая редакция теста сначала читала очередь «до паузы» и
    # потом удивлялась, что после снятия паузы там пусто — забрала сама. Здесь
    # наличие задания проверяем по БАЗЕ, а выдачу зовём ровно дважды: под
    # паузой и после неё.
    assert_eq(await _count_actions(db, CHANNEL_ID) > 0, True,
              "задание стоит в очереди до паузы")

    await _set_pause(db, CHANNEL_ID, True)
    during = await pending_actions_unless_paused(db, CHANNEL_ID, "bannerlord", 0, 50)
    assert_eq(during, [], "на паузе мод не получает ничего")

    await _set_pause(db, CHANNEL_ID, False)
    after = await pending_actions_unless_paused(db, CHANNEL_ID, "bannerlord", 0, 50)
    assert_eq(len(after) > 0, True, "снятие паузы вернуло очередь моду")


async def _run():
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_actions_pause_")
    os.close(fd)
    db = await _build_db(db_path)
    from routes.bannerlord import _bannerlord_buy_action_locked as buy
    try:
        await test_pause_refuses_before_charge(db, buy)
        await test_unpaused_not_blocked(db, buy)
        await test_pause_is_per_channel(db, buy)
        await test_queue_not_handed_to_mod(db)
    finally:
        # Пул закрывать ОБЯЗАТЕЛЬНО и именно так (`db._pool.close`): 28.08 тест
        # денег висел до таймаута ровно потому, что пул остался открытым.
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
    print("ВСЁ ЗЕЛЁНОЕ — аварийная остановка держит обе стороны")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
