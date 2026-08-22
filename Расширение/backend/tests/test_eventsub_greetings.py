"""
test_eventsub_greetings.py — рейды, биты и заявка в тестеры.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_eventsub_greetings.py

Что здесь проверяется и почему именно это:

1. РЕЙД и БИТЫ пишут в чат осмысленный текст. Отдельно — рейд с нулём
   зрителей (поле бывает пустым, и «рейд на 0 человек» читается как поломка)
   и анонимный чир (ника нет вовсе — наивный код напишет «@None»).

2. БИТЫ НЕ ДАЮТ ВАЛЮТЫ. Это не стилистика, это соответствие правилам Twitch:
   выдача игровой выгоды за биты — продажа преимущества мимо платёжной
   системы, тот же класс, из-за которого в мае вырезали казино. Тест держит
   границу: после чира баланс зрителя обязан остаться прежним.

3. ЗАЯВКА В ТЕСТЕРЫ отвечает зрителю и называет ник стримеру. 20.08 зритель
   @zerohomes потратил баллы на награду, которой не было в конфиге, и получил
   ровно ничего — ни доступа, ни ответа. Повтор той же выдачи (ретрай вебхука)
   не должен писать в чат второй раз.
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

_failures: list = []


def check(cond: bool, label: str):
    if cond:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label}")
        _failures.append(label)


class StubBot:
    """Ловит всё, что бот попытался написать в чат."""

    def __init__(self):
        self.sent: list = []

    async def send_message(self, text, channel_id=None):
        self.sent.append((channel_id, text))


CH = 4242
USER = "viewer_one"


async def _fresh_db(path: str):
    from database import Database
    db = Database(db_path=path)
    await db.init_pool()
    async with db._connect() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS channel_points_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                twitch_redemption_id TEXT NOT NULL,
                reward_title TEXT NOT NULL,
                channel_points_spent INTEGER NOT NULL,
                diamonds_given INTEGER NOT NULL,
                redeemed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(channel_id, twitch_redemption_id)
            )""")
        # Реальная таблица баланса. Без неё проверка «биты не начислили валюту»
        # была бы бессмысленной: запрос падал бы, а не показывал ноль.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS viewers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL DEFAULT 0,
                username TEXT NOT NULL,
                points INTEGER DEFAULT 0,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                join_time DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_afk INTEGER DEFAULT 0,
                UNIQUE(channel_id, username)
            )""")
        await conn.execute(
            "INSERT INTO viewers (channel_id, username, points) VALUES (?,?,?)",
            (CH, USER, 500),
        )
        await conn.commit()
    return db


async def _points(db, username: str) -> int:
    """Баланс крустиков. Отсутствие строки = 0."""
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT points FROM viewers WHERE channel_id=? AND username=?",
            (CH, username),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def run() -> int:
    import dependencies
    import eventsub as es

    db_path = tempfile.mktemp(suffix="_greet.db")
    db = await _fresh_db(db_path)
    bot = StubBot()
    dependencies.set_db(db)
    dependencies.set_bot(bot)

    # ── Рейд ────────────────────────────────────────────────────────────────
    print("\n[1] Рейд")
    bot.sent.clear()
    await es._on_channel_raid(
        {"from_broadcaster_user_login": "raider_bob", "viewers": 37}, CH)
    text = bot.sent[-1][1] if bot.sent else ""
    check("raider_bob" in text and "37" in text, f"назван рейдер и число зрителей: {text!r}")

    bot.sent.clear()
    await es._on_channel_raid({"from_broadcaster_user_login": "raider_bob"}, CH)
    text = bot.sent[-1][1] if bot.sent else ""
    check(bool(text) and "0" not in text,
          f"пустое поле viewers не превращается в «рейд на 0 человек»: {text!r}")

    bot.sent.clear()
    await es._on_channel_raid({"from_broadcaster_user_login": ""}, CH)
    check(not bot.sent, "рейд без ника в чат не пишет")

    # ── Биты ────────────────────────────────────────────────────────────────
    print("\n[2] Биты")
    bot.sent.clear()
    before = await _points(db, USER)
    await es._on_channel_cheer({"user_login": USER, "bits": 100}, CH)
    text = bot.sent[-1][1] if bot.sent else ""
    check(USER in text and "100" in text, f"назван зритель и число бит: {text!r}")
    check(await _points(db, USER) == before,
          "биты НЕ начисляют валюту (продажа преимущества запрещена Twitch)")

    bot.sent.clear()
    await es._on_channel_cheer({"is_anonymous": True, "bits": 50}, CH)
    text = bot.sent[-1][1] if bot.sent else ""
    check("None" not in text and "50" in text,
          f"анонимный чир не пишет «@None»: {text!r}")

    bot.sent.clear()
    await es._on_channel_cheer({"user_login": USER, "bits": 0}, CH)
    check(not bot.sent, "нулевые биты игнорируются")

    # ── Заявка в тестеры ────────────────────────────────────────────────────
    print("\n[3] Заявка в тестеры расширения")
    from config import CHANNEL_POINTS_CONFIG
    title = next(iter(CHANNEL_POINTS_CONFIG.get("tester_request_titles", ())), None)
    check(title is not None, "в конфиге есть хотя бы одно название заявки")

    bot.sent.clear()
    before = await _points(db, USER)
    await es._on_channel_points(
        {"user_login": USER, "id": "redemption-1",
         "reward": {"title": title}}, CH)
    text = bot.sent[-1][1] if bot.sent else ""
    check(USER in text, f"зрителю ответили и ник назван стримеру: {text!r}")
    check(await _points(db, USER) == before,
          "заявка НЕ начисляет крустиков (это не обмен, а заявка)")

    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT diamonds_given FROM channel_points_log "
            "WHERE channel_id=? AND twitch_redemption_id=?", (CH, "redemption-1"))
        row = await cur.fetchone()
    check(row is not None and int(row[0]) == 0, "заявка записана в журнал с 0 крустиков")

    bot.sent.clear()
    await es._on_channel_points(
        {"user_login": USER, "id": "redemption-1",
         "reward": {"title": title}}, CH)
    check(not bot.sent, "повторная доставка того же вебхука не пишет в чат второй раз")

    bot.sent.clear()
    await es._on_channel_points(
        {"user_login": USER, "id": "redemption-2",
         "reward": {"title": "какая-то чужая награда"}}, CH)
    check(not bot.sent, "неизвестная награда по-прежнему игнорируется молча")

    # Закрывать ИМЕННО так: метода close_pool() у Database нет, а обёрнутый в
    # except неверный вызов молча оставлял пул живым, и процесс висел до
    # таймаута с уже напечатанным «всё зелёное» (CLAUDE.md, правило 2c).
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


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
