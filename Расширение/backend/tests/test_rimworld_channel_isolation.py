# -*- coding: utf-8 -*-
"""RimWorld-таблицы не должны течь между каналами.

Четыре таблицы модуля жили без `channel_id` — наследие эпохи одного стримера.
Пока канал один, это невидимо; на втором рвётся сразу:

  * `shop_catalog` — заливка делала `DELETE FROM shop_catalog` без условия, то
    есть стирала каталог ВСЕМ стримерам. Второй запустил игру — у первого
    магазин опустел.
  * `rimworld_event_catalog` — `id` был глобально уникален: событие с тем же
    идентификатором у другого стримера перезаписывало чужое.
  * `purchase_counters` — ключ (username, category). Зритель с тем же ником на
    двух каналах делил счётчик прогрессивных цен: накупил генов у A — у B цены
    сразу высокие.
  * `rimworld_heal_cooldowns` — ключ (username). Полечился у A — кулдаун висел
    и у B.

Чинит миграция M97. Тест проверяет ПОСЛЕДСТВИЯ, а не наличие колонки: колонку
можно добавить и всё равно течь, если запросы её не используют.

Запуск:  python tests/test_rimworld_channel_isolation.py
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
os.environ.setdefault("TWITCH_BROADCASTER_ID", "98319857")

CHAN_A = 98319857          # существующий стример
CHAN_B = 555000111         # «второй стример», на котором всё и рвалось
USER = "sameviewer"        # один и тот же ник на обоих каналах — это норма

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

    db_path = os.path.join(tempfile.mkdtemp(prefix="rwiso_"), "t.db")
    db = database_mod.Database(db_path)
    await db.init_tables()
    async with aiosqlite.connect(db_path) as c:
        await m1_multitenant.apply(c)
        await c.commit()
    await db.init_tables()      # как на проде: следующий старт воссоздаёт снесённое
    async with aiosqlite.connect(db_path) as c:
        await m97_rimworld_tenant_scope.apply(c)
    return db, db_path


async def main():
    import aiosqlite
    import rimworld as rw   # noqa: F401 — нужен, чтобы DDL ленивых таблиц совпадал

    db, db_path = await build_db()

    # ── 1. Каталог магазина: заливка канала B не должна стирать каталог A ────
    async with aiosqlite.connect(db_path) as c:
        for ch, name in ((CHAN_A, "ItemOfA"), (CHAN_B, "ItemOfB")):
            await c.execute(
                "INSERT INTO shop_catalog (channel_id, category, def_name, label, price) "
                "VALUES (?, 'misc', ?, ?, 100)", (ch, name, name))
        await c.commit()

        # ровно то, что делает обработчик заливки для канала B
        await c.execute("DELETE FROM shop_catalog WHERE channel_id = ?", (CHAN_B,))
        await c.commit()

        cur = await c.execute(
            "SELECT COUNT(*) FROM shop_catalog WHERE channel_id = ?", (CHAN_A,))
        left_a = (await cur.fetchone())[0]
    check(left_a == 1,
          "каталог канала A ПЕРЕЖИЛ заливку каталога B (осталось позиций: %d)" % left_a)

    # ── 2. Один def_name может существовать на обоих каналах ────────────────
    ok_dup = True
    try:
        async with aiosqlite.connect(db_path) as c:
            for ch in (CHAN_A, CHAN_B):
                await c.execute(
                    "INSERT INTO shop_catalog (channel_id, category, def_name, label, price) "
                    "VALUES (?, 'misc', 'SharedDef', 'Общий предмет', 50)", (ch,))
            await c.commit()
    except Exception as e:
        ok_dup = False
        print("     (вставка упала: %s)" % e)
    check(ok_dup, "один и тот же предмет может быть у ДВУХ стримеров сразу "
                  "(UNIQUE по каналу, не глобально)")

    # ── 3. Счётчик прогрессивных цен не общий ───────────────────────────────
    await db.increment_purchase_count(USER, "gene", CHAN_A)
    await db.increment_purchase_count(USER, "gene", CHAN_A)
    a_count = await db.get_purchase_count(USER, "gene", CHAN_A)
    b_count = await db.get_purchase_count(USER, "gene", CHAN_B)
    check(a_count == 2, "у канала A счётчик вырос до 2 (получили %d)" % a_count)
    check(b_count == 0,
          "у канала B счётчик НЕ ТРОНУТ: цены у второго стримера начинаются "
          "с базовых (ожидали 0, получили %d)" % b_count)

    a_price = db.calc_progressive_price(1000, a_count)
    b_price = db.calc_progressive_price(1000, b_count)
    check(b_price < a_price,
          "зритель у второго стримера платит базовую цену, а не накрученную "
          "покупками у первого (%d против %d)" % (b_price, a_price))

    # ── 4. Кулдаун лечения не общий ─────────────────────────────────────────
    rw_mod = sys.modules["rimworld"]
    rw_mod.get_db = lambda: db
    await rw_mod._set_last_heal_ts(USER, 1_000_000.0, CHAN_A)
    ts_a = await rw_mod._get_last_heal_ts(USER, CHAN_A)
    ts_b = await rw_mod._get_last_heal_ts(USER, CHAN_B)
    check(ts_a > 0, "кулдаун записался на канале A (%s)" % ts_a)
    check(ts_b == 0,
          "на канале B кулдауна НЕТ: лечение у одного стримера не блокирует "
          "лечение у другого (получили %s)" % ts_b)

    # ── 5. Каталог событий: одинаковый id на разных каналах ─────────────────
    ok_ev = True
    try:
        async with aiosqlite.connect(db_path) as c:
            for ch in (CHAN_A, CHAN_B):
                await c.execute(
                    "INSERT INTO rimworld_event_catalog "
                    "(channel_id, id, name, cost, cmd, params, category) "
                    "VALUES (?, 'raid', 'Рейд', 500, 'fire_incident', '{}', 'threat')",
                    (ch,))
            await c.commit()
            cur = await c.execute("SELECT COUNT(*) FROM rimworld_event_catalog")
            total = (await cur.fetchone())[0]
    except Exception as e:
        ok_ev, total = False, -1
        print("     (вставка упала: %s)" % e)
    check(ok_ev and total == 2,
          "событие с одним id живёт на обоих каналах и не перезаписывает чужое "
          "(строк: %s)" % total)

    print("=" * 70)
    print("PASSED: %d   FAILED: %d" % (passed, failed))
    if failed:
        print("КРАСНО — модуль течёт между каналами, второй стример это сломает.")
    else:
        print("ALL GREEN — каналы изолированы.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
