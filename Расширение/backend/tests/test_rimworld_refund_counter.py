# -*- coding: utf-8 -*-
"""Рефанд обязан откатывать счётчик покупок, иначе зритель платит за воздух.

Цены на гены и черты ПРОГРЕССИВНЫЕ: каждая следующая покупка дороже
(`calc_progressive_price(base, count)`). Счётчик растёт в момент покупки
(`rimworld.py:1472` для гена, `:1740` для черты).

Баг: если мод отказался выполнять команду, `_refund_cmd_row_tx` возвращает
крустики — а счётчик остаётся поднятым. Зритель видит «деньги вернули, всё
честно», но его СЛЕДУЮЩИЙ ген стоит дороже. Навсегда, за покупку, которой не
было. Связать одно с другим он не может: рефанд сегодня, переплата через неделю.

Тест проверяет ровно это: баланс вернулся И цена следующей покупки не выросла.

Запуск:  python tests/test_rimworld_refund_counter.py
"""
import asyncio
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

os.environ.setdefault("TWITCH_OAUTH_TOKEN", "x")
os.environ.setdefault("TWITCH_CLIENT_ID", "x")
os.environ.setdefault("TWITCH_CLIENT_SECRET", "x")
os.environ.setdefault("TWITCH_BOT_ID", "x")
# m1 без него отказывается backfill'ить существующие строки.
os.environ.setdefault("TWITCH_BROADCASTER_ID", "98319857")

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


async def main():
    import database as database_mod
    import json

    tmpdir = tempfile.mkdtemp(prefix="rwrefund_")
    db_path = os.path.join(tmpdir, "t.db")

    db = database_mod.Database(db_path)
    await db.init_tables()
    # channel_id в viewers приходит миграцией M1, а не init_tables.
    import aiosqlite
    from migrations import m1_multitenant
    async with aiosqlite.connect(db_path) as _c:
        await m1_multitenant.apply(_c)
        await _c.commit()
    # M1 сносит purchase_counters (переводя счётчики на rimworld_purchase_counters),
    # но КОД по-прежнему ходит в старую таблицу, а init_tables пересоздаёт её на
    # следующем старте. Так это и живёт на проде — воспроизводим один в один.
    # Расхождение записано в DEFERRED; чинить перед ревью Twitch не стали.
    await db.init_tables()
    # M97 привязывает счётчики к каналу.
    from migrations import m97_rimworld_tenant_scope
    async with aiosqlite.connect(db_path) as _c:
        await m97_rimworld_tenant_scope.apply(_c)

    CHANNEL = 98319857
    USER = "testviewer"
    BASE_GENE_PRICE = 1000

    await db.add_points(USER, 100_000, channel_id=CHANNEL)   # создаёт зрителя

    # ── покупка гена: списание + рост счётчика (как в rimworld.py) ──────────
    count_before = await db.get_purchase_count(USER, "gene", CHANNEL)
    price = db.calc_progressive_price(BASE_GENE_PRICE, count_before)
    balance_before = await db.get_points(USER, channel_id=CHANNEL)

    ok = await db.remove_points(USER, price, channel_id=CHANNEL)
    check(ok, "списание за ген прошло")
    await db.increment_purchase_count(USER, "gene", CHANNEL)

    count_after_buy = await db.get_purchase_count(USER, "gene", CHANNEL)
    check(count_after_buy == count_before + 1,
          "счётчик вырос после покупки (%d -> %d)" % (count_before, count_after_buy))

    price_next_if_kept = db.calc_progressive_price(BASE_GENE_PRICE, count_after_buy)
    check(price_next_if_kept > price,
          "цена прогрессивная: следующий ген дороже (%d -> %d)" % (price, price_next_if_kept))

    # ── мод отказался → рефанд ──────────────────────────────────────────────
    import rimworld as rw
    rw.get_db = lambda: db          # рефанд ходит в БД через get_db()

    cmd_json = json.dumps({
        "type": "add_gene",
        "id": "gene_test_1",
        "username": USER,
        "def_name": "TestGene",
        "price": price,
        "channel_id": CHANNEL,
    })

    async with db._connect() as conn:
        refunded = await rw._refund_cmd_row_tx(conn, "gene_test_1", cmd_json, "mod_refused")
        await conn.commit()
    check(refunded, "рефанд отработал")

    # ── ЧТО ПРОВЕРЯЕМ ───────────────────────────────────────────────────────
    balance_after = await db.get_points(USER, channel_id=CHANNEL)
    check(balance_after == balance_before,
          "баланс вернулся полностью (%d -> %d)" % (balance_before, balance_after))

    count_after_refund = await db.get_purchase_count(USER, "gene", CHANNEL)
    check(count_after_refund == count_before,
          "СЧЁТЧИК ОТКАЧЕН: покупки не было, значит счётчик не должен был вырасти "
          "(ожидали %d, получили %d)" % (count_before, count_after_refund))

    price_next = db.calc_progressive_price(BASE_GENE_PRICE, count_after_refund)
    check(price_next == price,
          "СЛЕДУЮЩИЙ ГЕН СТОИТ СТОЛЬКО ЖЕ: зритель не наказан ценой за покупку, "
          "которой не было (ожидали %d, получили %d)" % (price, price_next))

    # ── то же для черты ─────────────────────────────────────────────────────
    BASE_TRAIT_PRICE = 1000
    t_before = await db.get_purchase_count(USER, "trait", CHANNEL)
    t_price = db.calc_progressive_price(BASE_TRAIT_PRICE, t_before)
    await db.remove_points(USER, t_price, channel_id=CHANNEL)
    await db.increment_purchase_count(USER, "trait", CHANNEL)

    cmd_json_t = json.dumps({
        "type": "add_trait",
        "id": "trait_test_1",
        "username": USER,
        "def_name": "TestTrait",
        "price": t_price,
        "channel_id": CHANNEL,
    })
    async with db._connect() as conn:
        await rw._refund_cmd_row_tx(conn, "trait_test_1", cmd_json_t, "mod_refused")
        await conn.commit()

    t_after = await db.get_purchase_count(USER, "trait", CHANNEL)
    check(t_after == t_before,
          "счётчик ЧЕРТ тоже откачен (ожидали %d, получили %d)" % (t_before, t_after))

    # ── страховка: рефанд команды БЕЗ счётчика ничего не ломает ─────────────
    h_before = await db.get_purchase_count(USER, "gene", CHANNEL)
    cmd_json_h = json.dumps({
        "type": "heal",
        "id": "heal_test_1",
        "username": USER,
        "price": 150,
        "channel_id": CHANNEL,
    })
    async with db._connect() as conn:
        await rw._refund_cmd_row_tx(conn, "heal_test_1", cmd_json_h, "mod_refused")
        await conn.commit()
    check(await db.get_purchase_count(USER, "gene", CHANNEL) == h_before,
          "рефанд команды без прогрессивной цены (heal) счётчик НЕ трогает")

    # ── страховка: счётчик не уходит в минус ───────────────────────────────
    async with db._connect() as conn:
        for _ in range(3):
            await db.decrement_purchase_count_tx(conn, USER, "gene", CHANNEL)
        await conn.commit()
    check(await db.get_purchase_count(USER, "gene", CHANNEL) >= 0,
          "счётчик не уходит в минус при лишних откатах")


    # 2026-07-26 — БЕЗ ЭТОГО ТЕСТ НЕ ЗАВЕРШАЕТСЯ. Пул соединений держит потоки,
    # которые интерпретатор обязан дождаться; тест печатает результат и висит
    # вечно. В CI это хуже падения: деплой-гейт ждёт бесконечно, красного никто
    # не видит. Прод закрывает пул сам (main.py на shutdown).
    # ВАЖНО: у каждого Database СВОЙ пул (`db._pool`). Закрывать надо именно
    # его — глобальный `close_db_pool()` здесь ни при чём и ничего не чинит
    # (проверено: потоков было 2, после него осталось 2, после db._pool.close() — 0).
    if getattr(db, "_pool", None):
        await db._pool.close()

    print("=" * 70)
    print("PASSED: %d   FAILED: %d" % (passed, failed))
    if failed:
        print("КРАСНО — зритель переплачивает после рефанда.")
    else:
        print("ALL GREEN — рефанд возвращает и деньги, и цену.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
