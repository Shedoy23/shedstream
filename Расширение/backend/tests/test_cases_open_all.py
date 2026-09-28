"""
test_cases_open_all.py — «Открыть все» отдаёт ровно столько, сколько должен.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_cases_open_all.py

## Зачем

05.09 у зрителей лежало 923 неоткрытых кейса на 1.1 млн крустиков — у одного
139 штук с мая. Открывать по одному никто не досиживал, и при этом зрители
жаловались, что крустиков не хватает. Кнопка «Открыть все» — деньги, поэтому
она проверяется как денежная операция, а не как UI-мелочь.

## Чего требуем

1. Открываются ВСЕ неоткрытые кейсы зрителя, начисляется сумма их наград.
2. Чужие кейсы не трогаются — ни открытием, ни начислением.
3. Уже открытые второй раз не платят (повторное нажатие даёт ноль).
4. Начисление и отметка «открыт» — одна транзакция: баланс сходится с суммой.
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

CH = 990177
ME = "open_all_me"
OTHER = "open_all_other"

fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  OK   " if ok else "  FAIL ") + name + ("" if ok else " — " + detail))
    if not ok:
        fails.append(name)


async def main() -> int:
    temp = tempfile.NamedTemporaryFile(prefix="shedlink-cases-open-all-", suffix=".db", delete=False)
    temp.close()
    db_path = Path(temp.name)
    os.environ["DB_PATH"] = str(db_path)

    from config import CASE_TIER_REWARDS
    from database import Database
    from dependencies import set_db
    import main as main_mod

    db = Database(str(db_path))
    await db.init_pool()
    set_db(db)

    # Тест обязан быть самостоятельным. Раньше он молча зависел от локального
    # viewers.db: на чистом checkout падал до первой проверки с `no such table:
    # cases`, а на машине разработчика мог затронуть настоящую dev-базу.
    await db.init_tables()
    await main_mod.run_migrations()

    async def cleanup():
        async with db._connect() as conn:
            await conn.execute("DELETE FROM cases WHERE channel_id=?", (CH,))
            await conn.execute("DELETE FROM viewers WHERE channel_id=?", (CH,))
            await conn.commit()

    try:
        await cleanup()
        async with db._connect() as conn:
            for user, points in ((ME, 0), (OTHER, 0)):
                await conn.execute(
                    "INSERT INTO viewers (channel_id, username, points, last_seen, join_time, is_afk) "
                    "VALUES (?,?,?,datetime('now'),datetime('now'),0)", (CH, user, points))
            for tier in ("common", "common", "rare", "epic"):
                await conn.execute(
                    "INSERT INTO cases (channel_id, username, tier, source) VALUES (?,?,?,'quest')",
                    (CH, ME, tier))
            await conn.execute(
                "INSERT INTO cases (channel_id, username, tier, source) VALUES (?,?,'legendary','quest')",
                (CH, OTHER,))
            await conn.commit()

        expected = 2 * CASE_TIER_REWARDS["common"] + CASE_TIER_REWARDS["rare"] + CASE_TIER_REWARDS["epic"]

        res = await db.open_all_cases(ME, channel_id=CH)
        check("открылись все четыре кейса", res["opened"] == 4, str(res))
        check("начислена сумма их наград", res["total_reward"] == expected,
              f"{res['total_reward']} вместо {expected}")
        check("баланс сошёлся с начислением", res["new_balance"] == expected, str(res["new_balance"]))
        check("не осталось неоткрытых", res["left"] == 0, str(res["left"]))

        again = await db.open_all_cases(ME, channel_id=CH)
        check("повторное нажатие ничего не платит",
              again["opened"] == 0 and again["total_reward"] == 0, str(again))

        async with db._connect() as conn:
            cur = await conn.execute(
                "SELECT opened_at FROM cases WHERE channel_id=? AND username=?", (CH, OTHER))
            other_rows = await cur.fetchall()
            cur = await conn.execute(
                "SELECT points FROM viewers WHERE channel_id=? AND username=?", (CH, OTHER))
            other_points = (await cur.fetchone())[0]
            cur = await conn.execute(
                "SELECT points FROM viewers WHERE channel_id=? AND username=?", (CH, ME))
            my_points = (await cur.fetchone())[0]

        check("чужой кейс остался закрытым", all(r[0] is None for r in other_rows))
        check("чужому ничего не начислено", other_points == 0, str(other_points))
        check("мой баланс равен сумме наград", my_points == expected, str(my_points))
    finally:
        await cleanup()
        try:
            await db._pool.close()
        except Exception:
            pass
        db_path.unlink(missing_ok=True)

    print()
    if fails:
        print(f"ПРОВАЛЕНО: {len(fails)} — " + "; ".join(fails))
        return 1
    print("ВСЁ ЗЕЛЁНОЕ")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
