# -*- coding: utf-8 -*-
"""Двойной клик не должен списывать дважды.

Зритель жмёт «купить» два раза — лаг, нетерпение, случайный дабл-клик. Уходит
два одинаковых запроса, списывается дважды, а получает он одно. У Bannerlord это
закрыто клиентским идентификатором попытки; у RimWorld такого нет, и попросить
фронт нельзя — он заморожен на CDN.

Решение без фронта: два клика по одной кнопке дают побайтово одинаковую команду
(отличается только служебное `id`), поэтому ключ выводится из содержимого.

Проверяем ровно то, что важно зрителю:
  * второй клик НЕ списывает деньги;
  * ответ при этом УСПЕХ — он нажал на то, что сработало, ошибку показывать
    неправильно;
  * в очередь попадает ОДНА команда, а не две (иначе мод сделает действие дважды);
  * разные покупки НЕ склеиваются;
  * после окна защита отпускает — осознанная вторая покупка проходит.

Запуск:  python tests/test_rimworld_double_click.py
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
USER = "clicker"

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
    from migrations import (m1_multitenant, m97_rimworld_tenant_scope,
                            m98_rimworld_dedup_key)

    path = os.path.join(tempfile.mkdtemp(prefix="rwclick_"), "t.db")
    db = database_mod.Database(path)
    await db.init_tables()
    async with aiosqlite.connect(path) as c:
        await m1_multitenant.apply(c)
        await c.commit()
    await db.init_tables()
    async with aiosqlite.connect(path) as c:
        await m97_rimworld_tenant_scope.apply(c)
    async with aiosqlite.connect(path) as c:
        await m98_rimworld_dedup_key.apply(c)
    return db


async def queue_size(db):
    async with db._connect() as c:
        cur = await c.execute(
            "SELECT COUNT(*) FROM rimworld_pending_commands WHERE channel_id = ?",
            (CHANNEL,))
        return (await cur.fetchone())[0]


async def main():
    import time
    import rimworld as rw

    db = await build_db()
    rw.get_db = lambda: db

    START, PRICE = 100_000, 2_000
    await db.add_points(USER, START, channel_id=CHANNEL)

    def cmd(def_name="Gene_X", ts=None):
        return {"type": "add_gene",
                "id": "gene_%s_%d" % (USER, int(ts or time.time())),
                "username": USER, "def_name": def_name,
                "price": PRICE, "channel_id": CHANNEL}

    # ── первый клик ─────────────────────────────────────────────────────────
    ok1 = await rw._charge_and_enqueue(USER, CHANNEL, PRICE, cmd())
    bal1 = await db.get_points(USER, channel_id=CHANNEL)
    check(ok1, "первый клик прошёл")
    check(bal1 == START - PRICE,
          "списано один раз (%d -> %d)" % (START, bal1))

    # ── второй клик сразу же ────────────────────────────────────────────────
    ok2 = await rw._charge_and_enqueue(USER, CHANNEL, PRICE, cmd())
    bal2 = await db.get_points(USER, channel_id=CHANNEL)
    check(ok2 is True,
          "второй клик отвечает УСПЕХОМ (зритель нажал на то, что сработало)")
    check(bal2 == bal1,
          "ВТОРОГО СПИСАНИЯ НЕТ: баланс не изменился (%d)" % bal2)
    q = await queue_size(db)
    check(q == 1,
          "в очереди ОДНА команда, а не две — мод не сделает действие дважды "
          "(команд: %d)" % q)

    # ── другая покупка не склеивается ───────────────────────────────────────
    ok3 = await rw._charge_and_enqueue(USER, CHANNEL, PRICE, cmd("Gene_OTHER"))
    bal3 = await db.get_points(USER, channel_id=CHANNEL)
    check(ok3, "покупка ДРУГОГО гена прошла")
    check(bal3 == bal2 - PRICE,
          "за неё списано отдельно (%d -> %d)" % (bal2, bal3))
    check(await queue_size(db) == 2, "в очереди стало две разные команды")

    # ── другой зритель не задет ─────────────────────────────────────────────
    OTHER = "someoneelse"
    await db.add_points(OTHER, START, channel_id=CHANNEL)
    other_cmd = {"type": "add_gene", "id": "gene_other_1",
                 "username": OTHER, "def_name": "Gene_X",
                 "price": PRICE, "channel_id": CHANNEL}
    ok4 = await rw._charge_and_enqueue(OTHER, CHANNEL, PRICE, other_cmd)
    check(ok4 and await db.get_points(OTHER, channel_id=CHANNEL) == START - PRICE,
          "тот же ген у ДРУГОГО зрителя покупается нормально")

    # ── после окна защита отпускает ─────────────────────────────────────────
    # Двигаем «сейчас» назад, состарив строку — ждать по-настоящему в тесте
    # нельзя, он должен идти секунду.
    async with db._connect() as c:
        await c.execute(
            "UPDATE rimworld_pending_commands "
            "SET created_at = datetime('now', '-60 seconds') "
            "WHERE channel_id = ?", (CHANNEL,))
        await c.commit()

    bal_before = await db.get_points(USER, channel_id=CHANNEL)
    ok5 = await rw._charge_and_enqueue(USER, CHANNEL, PRICE,
                                       cmd(ts=time.time() + 100))
    bal_after = await db.get_points(USER, channel_id=CHANNEL)
    check(ok5 and bal_after == bal_before - PRICE,
          "спустя окно осознанная повторная покупка ПРОХОДИТ и списывается "
          "(%d -> %d)" % (bal_before, bal_after))

    if getattr(db, "_pool", None):
        await db._pool.close()

    print("=" * 70)
    print("PASSED: %d   FAILED: %d" % (passed, failed))
    print("ALL GREEN — за двойной клик платят один раз." if not failed
          else "КРАСНО — двойной клик списывает дважды.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
