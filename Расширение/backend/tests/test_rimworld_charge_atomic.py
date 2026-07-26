# -*- coding: utf-8 -*-
"""Списание крустиков и постановка команды должны быть неделимы.

Раньше это были два независимых коммита: `remove_points` на своём соединении,
затем `_db_enqueue_command` на другом. Если между ними падало — крустики
списаны, команды нет, и вернуть их не может даже авто-рефанд: он ищет строку
команды, а её не существует. Зритель просто теряет деньги, и в базе нет следа,
что он вообще платил.

Тест ломает вставку команды НАРОЧНО и проверяет, что баланс не пострадал.
Это то, что в живой игре не воспроизвести по заказу.

Запуск:  python tests/test_rimworld_charge_atomic.py
"""
import asyncio
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

for _k, _v in (("TWITCH_OAUTH_TOKEN", "x"), ("TWITCH_CLIENT_ID", "x"),
               ("TWITCH_CLIENT_SECRET", "x"), ("TWITCH_BOT_ID", "x"),
               ("TWITCH_BROADCASTER_ID", "98319857")):
    os.environ.setdefault(_k, _v)

CHANNEL = 98319857
USER = "atomicviewer"

passed = 0
failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print("  OK   %s" % msg)
    else:
        failed += 1
        print("  FAIL %s" % msg)


async def build_db():
    import aiosqlite
    import database as database_mod
    from migrations import m1_multitenant, m97_rimworld_tenant_scope

    path = os.path.join(tempfile.mkdtemp(prefix="rwatomic_"), "t.db")
    db = database_mod.Database(path)
    await db.init_tables()
    async with aiosqlite.connect(path) as c:
        await m1_multitenant.apply(c)
        await c.commit()
    await db.init_tables()
    async with aiosqlite.connect(path) as c:
        await m97_rimworld_tenant_scope.apply(c)
    return db


async def count_commands(db):
    async with db._connect() as c:
        cur = await c.execute(
            "SELECT COUNT(*) FROM rimworld_pending_commands WHERE channel_id = ?",
            (CHANNEL,))
        return (await cur.fetchone())[0]


async def main():
    import rimworld as rw

    db = await build_db()
    rw.get_db = lambda: db

    START = 10_000
    PRICE = 1_500
    await db.add_points(USER, START, channel_id=CHANNEL)

    def make_cmd(cmd_id):
        """У каждого сценария СВОЙ предмет.

        Отпечаток для защиты от двойного клика считается по содержимому команды
        БЕЗ поля `id`. Если у всех сценариев один и тот же предмет, второй и
        последующие вызовы — это, с точки зрения бэкенда, повторный клик по
        одной кнопке, и он честно откажется списывать. Раньше здесь стоял общий
        "TestItem", и тест начал проверять дедупликацию вместо атомарности.
        """
        return {"type": "equip_item", "id": cmd_id, "username": USER,
                "def_name": "Item_%s" % cmd_id, "price": PRICE,
                "channel_id": CHANNEL}

    # ── 1. Обычная покупка: деньги списаны, команда поставлена ──────────────
    ok = await rw._charge_and_enqueue(USER, CHANNEL, PRICE, make_cmd("cmd_ok_1"))
    bal = await db.get_points(USER, channel_id=CHANNEL)
    cmds = await count_commands(db)
    check(ok, "покупка прошла")
    check(bal == START - PRICE,
          "списано ровно %d (баланс %d -> %d)" % (PRICE, START, bal))
    check(cmds == 1, "команда легла в очередь (команд: %d)" % cmds)

    # ── 2. Не хватает денег: ничего не произошло ────────────────────────────
    bal_before = bal
    ok2 = await rw._charge_and_enqueue(USER, CHANNEL, 10 ** 9, make_cmd("cmd_poor"))
    check(ok2 is False, "покупка не по карману отклонена")
    check(await db.get_points(USER, channel_id=CHANNEL) == bal_before,
          "баланс не тронут при отказе")
    check(await count_commands(db) == 1,
          "команда НЕ поставлена, раз не оплачена")

    # ── 3. ГЛАВНОЕ: вставка команды падает ПОСЛЕ списания ───────────────────
    # Ровно тот момент, который раньше съедал деньги: списание уже
    # закоммичено, а команда не записалась.
    bal_before = await db.get_points(USER, channel_id=CHANNEL)
    cmds_before = await count_commands(db)

    async def boom(_conn):
        raise RuntimeError("имитация сбоя БД между списанием и командой")

    crashed = False
    try:
        await rw._charge_and_enqueue(USER, CHANNEL, PRICE,
                                     make_cmd("cmd_boom"), on_success=boom)
    except RuntimeError:
        crashed = True

    check(crashed, "сбой действительно произошёл (иначе тест ничего не проверил)")
    bal_after = await db.get_points(USER, channel_id=CHANNEL)
    check(bal_after == bal_before,
          "ДЕНЬГИ НА МЕСТЕ после сбоя: зритель не заплатил за несостоявшуюся "
          "покупку (было %d, стало %d)" % (bal_before, bal_after))
    check(await count_commands(db) == cmds_before,
          "команда тоже не появилась — состояние как до попытки")

    # ── 4. Побочное действие (счётчик цен) откатывается вместе со всем ──────
    before_cnt = await db.get_purchase_count(USER, "gene", CHANNEL)

    async def bump_then_fail(conn):
        await conn.execute(
            "INSERT INTO purchase_counters (channel_id, username, category, count) "
            "VALUES (?, ?, 'gene', 1) "
            "ON CONFLICT(channel_id, username, category) DO UPDATE SET count = count + 1",
            (CHANNEL, USER.lower()))
        raise RuntimeError("сбой уже ПОСЛЕ роста счётчика")

    try:
        await rw._charge_and_enqueue(USER, CHANNEL, PRICE,
                                     make_cmd("cmd_boom2"), on_success=bump_then_fail)
    except RuntimeError:
        pass
    check(await db.get_purchase_count(USER, "gene", CHANNEL) == before_cnt,
          "счётчик прогрессивных цен откатился вместе с транзакцией "
          "(был %d)" % before_cnt)

    # ── 5. Команда попадает в память только после успешного коммита ────────
    rw.get_pending().clear()
    try:
        await rw._charge_and_enqueue(USER, CHANNEL, PRICE,
                                     make_cmd("cmd_boom3"), on_success=boom)
    except RuntimeError:
        pass
    check(len(rw.get_pending()) == 0,
          "в память команда НЕ попала: мод не увидит того, чего нет в базе")

    # ── 6. Повтор ТОЙ ЖЕ покупки не списывает дважды ───────────────────────
    # Подтверждаем, что защита от двойного клика и атомарность уживаются:
    # одинаковое содержимое = повтор, разное = отдельные покупки.
    same = {"type": "equip_item", "id": "twin_a", "username": USER,
            "def_name": "TwinItem", "price": PRICE, "channel_id": CHANNEL}
    bal0 = await db.get_points(USER, channel_id=CHANNEL)
    await rw._charge_and_enqueue(USER, CHANNEL, PRICE, dict(same))
    bal1 = await db.get_points(USER, channel_id=CHANNEL)
    same["id"] = "twin_b"
    await rw._charge_and_enqueue(USER, CHANNEL, PRICE, dict(same))
    bal2 = await db.get_points(USER, channel_id=CHANNEL)
    check(bal1 == bal0 - PRICE and bal2 == bal1,
          "повтор той же покупки списал ОДИН раз (%d -> %d -> %d)"
          % (bal0, bal1, bal2))

    if getattr(db, "_pool", None):
        await db._pool.close()

    print("=" * 70)
    print("PASSED: %d   FAILED: %d" % (passed, failed))
    print("ALL GREEN — деньги и команда неделимы." if not failed
          else "КРАСНО — зритель может заплатить впустую.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
