"""
test_hourly_cases.py — часовая раздача кейсов: деньги, редкость, идемпотентность.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_hourly_cases.py

## Зачем

Решение владельца 05.09: раз в час каждый активный зритель получает кейс.
Повод — замер того же дня: на обычном эфире тратят 771k крустиков против 334k
заработанных, и разрыв затыкался разовыми промокодами.

Кейс — это деньги, поэтому проверяем как денежную операцию.

## Чего требуем

1. Кейс получает КАЖДЫЙ активный зритель, по одному за проход.
2. Второй проход в тот же час НЕ выдаёт повторно (перезапуск сервиса, ретрай).
3. Тот, кто «на связи», но ни разу не взаимодействовал, получает только
   обычный кейс — брошенная вкладка не фармит редкие (урок 28.08).
4. Неактивные (панель закрыта) не получают ничего.
5. Легендарка возможна, но её вес держится дробным: 1.0 (как у дропа) дал бы
   девять легендарок в месяц вместо одной.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

HERE = Path(__file__).parent.absolute()
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))

for _k, _v in (
    ("TWITCH_OAUTH_TOKEN", "oauth:test"), ("TWITCH_CLIENT_ID", "test_client"),
    ("TWITCH_CLIENT_SECRET", "test_secret"), ("TWITCH_BOT_ID", "test_bot"),
    ("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab"),
    ("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890"),
    ("ADMIN_PASSWORD", "test_admin_password_for_tests_only"),
):
    os.environ.setdefault(_k, _v)

CH = 990233
ACTIVE = "hourly_active"
LURKER = "hourly_lurker"
GONE = "hourly_gone"

fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  OK   " if ok else "  FAIL ") + name + ("" if ok else " — " + detail))
    if not ok:
        fails.append(name)


async def main() -> int:
    from config import HOURLY_CASE_TIERS
    from database import Database
    from dependencies import set_db
    import bot_core

    # Локальная viewers.db — та же, на которой работают соседние money-тесты.
    # Полный прогон миграций занимает минуты, поэтому недостающую колонку
    # (её добавляла поздняя миграция) досоздаём точечно.
    db = Database("viewers.db")
    await db.init_pool()
    async with db._connect() as conn:
        cur = await conn.execute("PRAGMA table_info(viewers)")
        cols = {r[1] for r in await cur.fetchall()}
        if "last_interaction_at" not in cols:
            await conn.execute("ALTER TABLE viewers ADD COLUMN last_interaction_at TIMESTAMP")
            await conn.commit()
    set_db(db)

    async def cleanup():
        async with db._connect() as conn:
            await conn.execute("DELETE FROM cases WHERE channel_id=?", (CH,))
            await conn.execute("DELETE FROM viewers WHERE channel_id=?", (CH,))
            await conn.execute("DELETE FROM case_triggers_fired WHERE channel_id=?", (CH,))
            await conn.commit()

    # Бот без сети: нам нужны только _process_hourly_cases и его зависимости.
    bot = bot_core.BotCore.__new__(bot_core.BotCore)
    bot.db = db
    sent: list = []

    async def _fake_send(text, channel_id=None):
        sent.append(text)

    async def _live(channel_id=None):
        return True

    bot.send_message = _fake_send
    bot._is_stream_live = _live

    try:
        await cleanup()
        async with db._connect() as conn:
            # активный: и на связи, и взаимодействовал
            await conn.execute(
                "INSERT INTO viewers (channel_id, username, points, last_seen, join_time, is_afk, last_interaction_at) "
                "VALUES (?,?,0,datetime('now'),datetime('now'),0,datetime('now'))", (CH, ACTIVE))
            # лёркер: панель на связи, взаимодействия не было никогда
            await conn.execute(
                "INSERT INTO viewers (channel_id, username, points, last_seen, join_time, is_afk, last_interaction_at) "
                "VALUES (?,?,0,datetime('now'),datetime('now'),0,NULL)", (CH, LURKER))
            # ушёл: панель закрыта час назад
            await conn.execute(
                "INSERT INTO viewers (channel_id, username, points, last_seen, join_time, is_afk, last_interaction_at) "
                "VALUES (?,?,0,datetime('now','-2 hours'),datetime('now'),0,NULL)", (CH, GONE))
            await conn.commit()

        await bot._process_hourly_cases(channel_id=CH)

        async with db._connect() as conn:
            cur = await conn.execute(
                "SELECT username, tier FROM cases WHERE channel_id=?", (CH,))
            rows = await cur.fetchall()
        by_user = {u: t for u, t in rows}

        check("активный получил кейс", ACTIVE in by_user, str(by_user))
        check("лёркер получил кейс", LURKER in by_user, str(by_user))
        check("лёркеру достался только обычный", by_user.get(LURKER) == "common",
              str(by_user.get(LURKER)))
        check("ушедший не получил ничего", GONE not in by_user, str(by_user))
        check("в чат ушла сводка", any("Часовые кейсы" in m for m in sent), str(sent))

        # второй проход в тот же час
        sent.clear()
        await bot._process_hourly_cases(channel_id=CH)
        async with db._connect() as conn:
            cur = await conn.execute("SELECT COUNT(*) FROM cases WHERE channel_id=?", (CH,))
            total = (await cur.fetchone())[0]
        check("повторный проход не выдал второй кейс", total == 2, f"кейсов {total}")
        check("и промолчал в чате", not sent, str(sent))

        weights = dict(HOURLY_CASE_TIERS)
        check("легендарка есть, но дробным весом",
              0 < weights.get("legendary", 0) <= 0.2,
              f"вес {weights.get('legendary')}")
    finally:
        await cleanup()
        try:
            await db._pool.close()
        except Exception:
            pass

    print()
    if fails:
        print(f"ПРОВАЛЕНО: {len(fails)} — " + "; ".join(fails))
        return 1
    print("ВСЁ ЗЕЛЁНОЕ")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
