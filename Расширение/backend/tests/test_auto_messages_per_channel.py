"""
test_auto_messages_per_channel.py — личные автосообщения не утекают в чужой чат.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_auto_messages_per_channel.py

ЗАЧЕМ. `AUTO_MESSAGES` рассылается ботом в чат КАЖДОГО канала из реестра. До
2026-08-22 в этом общем списке лежали DonationAlerts, Boosty и Telegram
владельца: второй стример получил бы в свой чат рекламу чужих донатов. С одним
каналом дефект невидим — поэтому его и не замечали.

Тест держит границу, которую нельзя проверить глазами:
  - у канала владельца личные сообщения ЕСТЬ (миграция их перенесла);
  - у любого другого канала их НЕТ — он видит только нейтральные;
  - общий список не содержит ссылок (дублирует линтер, но здесь — на рантайме).
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

OWNER_CH = 98319857
OTHER_CH = 555001          # «второй стример», ради которого всё и делается


def check(cond: bool, label: str):
    if cond:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label}")
        _failures.append(label)


async def run() -> int:
    from bot_core import BotCore
    from config import AUTO_MESSAGES
    from database import Database
    from migrations import m114_channel_auto_messages

    db_path = tempfile.mktemp(suffix="_automsg.db")
    db = Database(db_path=db_path)
    await db.init_pool()
    async with db._connect() as conn:
        await m114_channel_auto_messages.apply(conn)
        await conn.commit()

    bot = BotCore(db)

    print("\n[1] Общий список нейтрален")
    linky = [m for m in AUTO_MESSAGES
             if any(x in m for x in ("http://", "https://", "t.me/", "www."))]
    check(not linky, f"в общем списке нет ссылок (нашлось: {linky})")

    print("\n[2] Канал владельца")
    owner = await bot._channel_auto_messages(OWNER_CH)
    check(len(owner) >= 1, f"личные сообщения на месте ({len(owner)} шт.)")
    check(any("boosty" in m.lower() for m in owner),
          "личная ссылка на поддержку перенесена, а не потеряна")

    print("\n[3] Другой стример")
    other = await bot._channel_auto_messages(OTHER_CH)
    check(other == [],
          f"у чужого канала личных сообщений НЕТ (получено: {other})")

    # Самое главное: то, что реально уйдёт в чат каждому.
    owner_feed = list(AUTO_MESSAGES) + owner
    other_feed = list(AUTO_MESSAGES) + other
    leaked = [m for m in other_feed if "shedoy" in m.lower() or "boosty" in m.lower()]
    check(not leaked,
          f"в чат чужого стримера не уходит ничего личного (утечка: {leaked})")
    check(len(owner_feed) > len(other_feed),
          "у владельца лента шире — значит личное подмешивается именно ему")

    print("\n[4] Повторное применение миграции")
    async with db._connect() as conn:
        await m114_channel_auto_messages.apply(conn)
        await conn.commit()
    again = await bot._channel_auto_messages(OWNER_CH)
    check(len(again) == len(owner), "миграция идемпотентна — дублей не появилось")

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
