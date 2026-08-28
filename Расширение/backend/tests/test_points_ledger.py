"""
test_points_ledger.py — каждое движение крустиков оставляет след, включая возврат.

Standalone (без pytest). Запуск из backend/:
    python tests/test_points_ledger.py

ЗАЧЕМ. 28.08 на эфире `colonist.give_tools` (2500) упал с `unknown_action`,
код выполнил возврат — и доказать, что возврат начислен, было нечем: списаний и
возвратов не писала ни одна таблица. Подтверждение существовало строкой в логе,
а лог ротируется; по балансу тоже не проверить — параллельно капает watchtime.

Тест держит границы, которые легко потерять при следующей правке денег:

1. **Возврат доказуем.** Списали 2500, вернули 2500 — в журнале две строки и
   нулевая сумма. Это ровно тот вопрос, на который 28.08 не было ответа.
2. **Прямой `UPDATE viewers SET points` тоже попадает в журнал.** Через
   `add_points`/`remove_points` идут 17 мест, а мимо них — 22 в шести файлах.
   Журнал, который их не видит, ХУЖЕ отсутствия журнала: он выглядит полным.
3. **Атомарность.** Откат транзакции убирает и деньги, и строку журнала. Иначе
   журнал начнёт показывать списания, которых не было.
4. **Цепочка баланса не рвётся.** `balance_after` предыдущей строки равен
   `balance_before` следующей — это единственный способ заметить дыру в учёте,
   не доверяя учёту.
5. **Тишина на шуме.** Обновление `last_seen` (раз в минуту на каждого
   зрителя) строк не плодит, иначе журнал утонет.
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
os.environ.setdefault("TWITCH_BROADCASTER_ID", "4242")

_failures: list = []
CH = 4242
USER = "ledger_user"


def check(cond: bool, label: str):
    if cond:
        print(f"  OK   {label}")
    else:
        print(f"  FAIL {label}")
        _failures.append(label)


async def _rows(db, username: str = USER) -> list:
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT delta, balance_before, balance_after FROM points_ledger "
            "WHERE channel_id=? AND username=? ORDER BY id", (CH, username))
        return [tuple(r) for r in await cur.fetchall()]


async def _balance(db, username: str = USER) -> int:
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT points FROM viewers WHERE channel_id=? AND username=?",
            (CH, username))
        r = await cur.fetchone()
    return int(r[0]) if r else 0


async def run() -> int:
    from database import Database

    db_path = tempfile.mktemp(suffix="_ledger.db")
    db = Database(db_path=db_path)
    await db.init_pool()
    try:
        await _checks(db)
    except Exception as exc:                       # noqa: BLE001
        # Падение проверки — тоже результат, но только если о нём УЗНАЮТ.
        print(f"  FAIL исключение в проверках: {type(exc).__name__}: {exc}")
        _failures.append(f"{type(exc).__name__}: {exc}")
    finally:
        # Пул закрываем ВСЕГДА. Без finally первое же исключение — а прилетает
        # оно ровно тогда, когда журнал сломан и строк нет, — оставляет
        # соединения открытыми: тест не падает, а ВИСИТ, кода возврата не
        # наступает, деплой-гейт ждёт вечно. Ловушка описана в
        # RUNBOOK.md §7 «Ловушки»; поймана на своём же красном прогоне 28.08.
        await db._pool.close()
        try:
            os.unlink(db_path)
        except OSError:
            pass

    print("\n" + "=" * 58)
    if _failures:
        print(f"ПРОВАЛЕНО: {len(_failures)}")
        for f in _failures:
            print("  -", f)
        return 1
    print("Все проверки прошли")
    return 0


async def _checks(db) -> None:
    import dependencies
    from migrations import m1_multitenant, m118_points_ledger

    async with db._connect() as conn:
        # m1 ПЕРЕСОЗДАЁТ viewers — триггеры ставим после неё, иначе они
        # отвалились бы вместе со старой таблицей и тест проверял бы пустоту.
        await m1_multitenant.apply(conn)
        await m118_points_ledger.apply(conn)
        await conn.commit()
    dependencies.set_db(db)

    print("\n[1] Возврат доказуем: списали 2500, вернули 2500")
    await db.add_points(USER, 5000, channel_id=CH)
    ok = await db.remove_points(USER, 2500, channel_id=CH)
    await db.add_points(USER, 2500, channel_id=CH)      # рефанд
    check(ok, "списание прошло")
    rows = await _rows(db)
    deltas = [r[0] for r in rows]
    check(deltas == [5000, -2500, 2500],
          f"три движения записаны в порядке: {deltas}")
    check(deltas[1] + deltas[2] == 0,
          "списание и возврат в сумме дают ноль — возврат доказан")

    print("\n[2] Прямой UPDATE мимо add_points/remove_points тоже виден")
    # Так делают 22 места: аукционы Bannerlord, магазин ShedColony, рефанды в
    # адаптерах. Журнал, который их не видит, выглядит полным и врёт.
    before = len(rows)
    async with db._connect() as conn:
        await conn.execute(
            "UPDATE viewers SET points = points - ? WHERE channel_id=? AND username=?",
            (1000, CH, USER))
        await conn.commit()
    rows = await _rows(db)
    check(len(rows) == before + 1 and rows[-1][0] == -1000,
          f"сырой UPDATE записан ({rows[-1] if rows else 'строки нет'})")

    print("\n[3] Откат транзакции убирает и деньги, и строку журнала")
    before_rows, before_balance = len(await _rows(db)), await _balance(db)
    async with db._connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        await db.remove_points_tx(conn, USER, 700, CH)
        await conn.execute("ROLLBACK")
    check(await _balance(db) == before_balance, "деньги на месте после отката")
    check(len(await _rows(db)) == before_rows,
          "строки журнала о несостоявшемся списании нет")

    print("\n[4] _tx-версии на общем conn пишутся вместе с эффектом")
    async with db._connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        await db.remove_points_tx(conn, USER, 700, CH)
        await db.add_points_tx(conn, USER, 200, CH)
        await conn.commit()
    deltas = [r[0] for r in await _rows(db)]
    check(deltas[-2:] == [-700, 200], f"обе операции записаны: {deltas[-2:]}")

    print("\n[5] Цепочка баланса не рвётся")
    rows = await _rows(db)
    breaks = [i for i in range(1, len(rows)) if rows[i][1] != rows[i - 1][2]]
    check(not breaks,
          f"balance_after -> balance_before сходится на всех {len(rows)} строках")
    check(rows[-1][2] == await _balance(db),
          "последняя строка журнала совпадает с реальным балансом")

    print("\n[6] Новый зритель с ненулевым балансом записан с нуля")
    await db.add_points("fresh_viewer", 300, channel_id=CH)
    fresh = await _rows(db, "fresh_viewer")
    check(fresh == [(300, 0, 300)], f"первая строка новичка: {fresh}")

    print("\n[7] Обновление last_seen журнал не засоряет")
    before = len(await _rows(db))
    async with db._connect() as conn:
        for _ in range(5):
            await conn.execute(
                "UPDATE viewers SET last_seen=datetime('now') "
                "WHERE channel_id=? AND username=?", (CH, USER))
        await conn.commit()
    check(len(await _rows(db)) == before,
          "пять обновлений last_seen не добавили ни строки")

    print("\n[8] Триггеры на месте под своими именами")
    # Их сносит любая будущая миграция, которая ПЕРЕСОЗДАЁТ viewers (m1 это уже
    # делала). Молча: деньги продолжат ходить, журнал просто перестанет писаться.
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND name LIKE 'trg_points_ledger%'")
        names = sorted(r[0] for r in await cur.fetchall())
    check(names == ["trg_points_ledger_insert", "trg_points_ledger_update"],
          f"оба триггера существуют: {names}")


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
