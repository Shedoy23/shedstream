"""
test_new_channel_walkthrough.py — путь СОВСЕМ нового канала, целиком.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_new_channel_walkthrough.py

ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ, если куски уже покрыты другими тестами.

За 21–22 августа нашлось три дефекта одного класса: что-то одно на всю
платформу там, где должно быть по числу каналов (список автосообщений с
донат-ссылками владельца; объявление сезона в «канал по умолчанию»; анонс
любого эфира в Telegram владельца). Ни один не ловился существующими тестами,
потому что каждый отдельный кусок был корректен — неверным было ЦЕЛОЕ: как
выглядит система глазами второго арендатора.

Этот файл и есть тот второй арендатор. Он проходит путь новичка по порядку —
регистрация, ворота одобрения, чат-бот, автосообщения, внешние оповещения — и
на каждом шаге спрашивает одно: «не досталось ли ему чужого и не утекло ли его
чужим». Владелец сформулировал рамку так: мы делаем платформу, а не проектик
под одного стримера. Здесь эта рамка проверяется машиной.
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

OWNER_CH, OWNER_LOGIN = 98319857, "shedoy23"
NEW_CH, NEW_LOGIN = 777001, "newcomer"

# Всё, по чему узнаётся владелец. Если хоть одно всплывёт у новичка — это
# ровно тот дефект, ради которого файл написан.
OWNER_MARKERS = ("shedoy", "boosty", "donationalerts", "ttvshedoy")


def check(cond: bool, label: str):
    if cond:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label}")
        _failures.append(label)


def _owner_traces(values) -> list:
    out = []
    for v in values:
        low = str(v).lower()
        if any(m in low for m in OWNER_MARKERS):
            out.append(v)
    return out


async def run() -> int:
    import dependencies
    from database import Database
    from main import channels_to_join
    from migrations import (
        m4_channels,
        m99_channel_approval,
        m114_channel_auto_messages,
        m115_auto_message_timers,
    )

    db_path = tempfile.mktemp(suffix="_walkthrough.db")
    db = Database(db_path=db_path)
    await db.init_pool()
    async with db._connect() as conn:
        await m4_channels.apply(conn)
        await m99_channel_approval.apply(conn)
        await m114_channel_auto_messages.apply(conn)
        await m115_auto_message_timers.apply(conn)
        await conn.commit()
    dependencies.set_db(db)

    # Владелец в реестре и одобрен — как на проде.
    await db.upsert_channel(channel_id=OWNER_CH, login=OWNER_LOGIN)
    await db.set_channel_approved(OWNER_CH, True)

    print("\n[1] Новичок зарегистрировался")
    await db.upsert_channel(channel_id=NEW_CH, login=NEW_LOGIN)
    rows = {r["channel_id"]: r for r in await db.list_channels()}
    check(NEW_CH in rows, "канал появился в реестре")
    check(not rows[NEW_CH].get("approved"),
          "и пришёл НЕ одобренным — ворота на месте")

    print("\n[2] Пока не одобрен — бот к нему не идёт")
    # Ворота одобрения существуют затем, чтобы неподготовленный канал не
    # получал обслуживания. Бот, сидящий в чате, — это обслуживание.
    approved_logins = [r["login"] for r in await db.list_channels() if r.get("approved")]
    check(NEW_LOGIN not in channels_to_join(approved_logins, [OWNER_LOGIN]),
          "неодобренный канал в список захода не попал")

    print("\n[3] Одобрили — бот заходит БЕЗ рестарта бэкенда")
    await db.set_channel_approved(NEW_CH, True)
    approved_logins = [r["login"] for r in await db.list_channels() if r.get("approved")]
    to_join = channels_to_join(approved_logins, [OWNER_LOGIN])
    check(to_join == [NEW_LOGIN],
          f"дозаходим ровно к новичку (получено: {to_join})")

    print("\n[4] Автосообщения новичка — его собственные")
    await db.seed_channel_auto_messages(NEW_CH)
    new_msgs = [m["text"] for m in await db.get_channel_auto_messages(NEW_CH)]
    owner_msgs = [m["text"] for m in await db.get_channel_auto_messages(OWNER_CH)]
    check(bool(new_msgs), f"набор не пустой — есть что показать в дашборде ({len(new_msgs)})")
    traces = _owner_traces(new_msgs)
    check(not traces, f"в них НЕТ ничего про владельца (найдено: {traces})")
    check(all(m["interval_min"] > 0 for m in await db.get_channel_auto_messages(NEW_CH)),
          "у каждого сообщения есть таймер")

    print("\n[5] Правки новичка не трогают владельца")
    before_owner = list(owner_msgs)
    await db.set_channel_auto_messages(NEW_CH, [
        {"text": "Заходите ко мне в дискорд", "interval_min": 30},
    ])
    after_owner = [m["text"] for m in await db.get_channel_auto_messages(OWNER_CH)]
    check(after_owner == before_owner,
          "набор владельца не изменился, пока новичок правил свой")
    new_after = [m["text"] for m in await db.get_channel_auto_messages(NEW_CH)]
    check(new_after == ["Заходите ко мне в дискорд"],
          f"у новичка ровно то, что он сохранил (получено: {new_after})")

    print("\n[6] Эфир новичка не анонсируется аудитории владельца")
    import notifications

    os.environ["TELEGRAM_NOTIFICATIONS_ENABLED"] = "true"
    os.environ["TELEGRAM_BOT_TOKEN"] = "test-token"
    os.environ["TELEGRAM_CHAT_ID"] = "@test"
    os.environ["TELEGRAM_NOTIFY_CHANNEL_ID"] = str(OWNER_CH)
    posted = []

    class _StubSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def post(self, url, **kw):
            posted.append(url)
            raise RuntimeError("сюда доходить не должно")

    real = notifications.aiohttp.ClientSession
    notifications.aiohttp.ClientSession = _StubSession
    try:
        await notifications.notify_stream_online(NEW_CH, NEW_LOGIN)
        check(not posted, f"в Telegram владельца ничего не ушло (запросов: {len(posted)})")
    finally:
        notifications.aiohttp.ClientSession = real
        for key in ("TELEGRAM_NOTIFICATIONS_ENABLED", "TELEGRAM_BOT_TOKEN",
                    "TELEGRAM_CHAT_ID", "TELEGRAM_NOTIFY_CHANNEL_ID"):
            os.environ.pop(key, None)

    print("\n[7] Закрыли новичка — бот уходить не обязан, но заново не лезет")
    await db.set_channel_approved(NEW_CH, False)
    approved_logins = [r["login"] for r in await db.list_channels() if r.get("approved")]
    check(NEW_LOGIN not in channels_to_join(approved_logins, [OWNER_LOGIN, NEW_LOGIN]),
          "после закрытия канал не попадает в список повторного захода")

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
