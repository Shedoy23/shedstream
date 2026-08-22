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
    from migrations import m114_channel_auto_messages, m115_auto_message_timers

    db_path = tempfile.mktemp(suffix="_automsg.db")
    db = Database(db_path=db_path)
    await db.init_pool()
    async with db._connect() as conn:
        await m114_channel_auto_messages.apply(conn)
        await m115_auto_message_timers.apply(conn)
        await conn.commit()

    bot = BotCore(db)

    print("\n[1] Общий список нейтрален")
    linky = [m for m in AUTO_MESSAGES
             if any(x in m for x in ("http://", "https://", "t.me/", "www."))]
    check(not linky, f"в общем списке нет ссылок (нашлось: {linky})")

    print("\n[2] Канал владельца")
    owner = [m["text"] for m in await db.get_channel_auto_messages(OWNER_CH)]
    check(len(owner) >= 1, f"личные сообщения на месте ({len(owner)} шт.)")
    check(any("boosty" in m.lower() for m in owner),
          "личная ссылка на поддержку перенесена, а не потеряна")

    print("\n[3] Другой стример")
    other = [m["text"] for m in await db.get_channel_auto_messages(OTHER_CH)]
    check(other == [],
          f"у чужого канала личных сообщений НЕТ (получено: {other})")

    # Главное: в набор чужого канала не попало ничего личного.
    leaked = [m for m in other if "shedoy" in m.lower() or "boosty" in m.lower()]
    check(not leaked,
          f"в чат чужого стримера не уходит ничего личного (утечка: {leaked})")

    print("\n[4] Миграция отметилась в журнале")
    # Без этой записи миграция гоняется на каждом старте, а её INSERT'ы не
    # коммитятся — именно так 22.08 таблица приехала на прод пустой.
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT 1 FROM migrations_applied WHERE name LIKE 'M114%'")
        recorded = await cur.fetchone()
    check(recorded is not None, "M114 записана в migrations_applied")

    print("\n[5] Повторное применение миграции")
    async with db._connect() as conn:
        await m114_channel_auto_messages.apply(conn)
        await conn.commit()
    again = [m["text"] for m in await db.get_channel_auto_messages(OWNER_CH)]
    check(len(again) == len(owner), "миграция идемпотентна — дублей не появилось")

    # ── Таймеры (m115) ──────────────────────────────────────────────────────
    import time as _t

    print("\n[6] У каждого сообщения свой таймер")
    async with db._connect() as conn:
        from migrations import m115_auto_message_timers
        await m115_auto_message_timers.apply(conn)
        await conn.commit()

    saved = await db.set_channel_auto_messages(OTHER_CH, [
        {"text": "часто", "interval_min": 10, "enabled": True},
        {"text": "редко", "interval_min": 120, "enabled": True},
        {"text": "выключено", "interval_min": 10, "enabled": False},
    ])
    check(len(saved) == 3, f"сохранились все три строки ({len(saved)})")
    check([m["interval_min"] for m in saved] == [10, 120, 10],
          "интервалы сохранились каждый свой")

    bot_other = BotCore(db)
    print("\n[7] Первый тик заводит отсчёт, но НЕ шлёт")
    # Иначе на старте эфира разом «просрочены» все строки и канал получает
    # пачку — Twitch считает это спамом и таймаутит бота.
    first = await bot_other._due_auto_message(OTHER_CH)
    check(first is None, f"на первом тике ничего не отправлено (получено: {first})")
    rows = await db.get_channel_auto_messages(OTHER_CH)
    check(all(r["last_sent_at"] is not None for r in rows if r["enabled"]),
          "но отсчёт заведён у всех ВКЛЮЧЁННЫХ строк")
    # Выключенная строка отсчёта не получает — и это правильно: её включат
    # позже, и считать интервал надо с момента включения, а не с давнего
    # прошлого, иначе она выстрелит в ту же секунду.
    off = next(r for r in rows if not r["enabled"])
    check(off["last_sent_at"] is None, "выключенная строка отсчёт не начинает")

    print("\n[8] Срабатывает только то, чей срок вышел")
    now = _t.time()
    await db.mark_auto_message_sent(OTHER_CH, 0, now - 11 * 60)   # «часто» просрочено
    await db.mark_auto_message_sent(OTHER_CH, 1, now - 11 * 60)   # «редко» ещё нет
    due = await bot_other._due_auto_message(OTHER_CH)
    check(due is not None and due["text"] == "часто",
          f"выбрано сообщение с истёкшим таймером (получено: {due and due['text']})")

    await db.mark_auto_message_sent(OTHER_CH, 0, now)             # «часто» отправлено
    due = await bot_other._due_auto_message(OTHER_CH)
    check(due is None, "после отправки очередь пуста — пачкой не сыпем")

    print("\n[9] Выключенное не уходит никогда")
    await db.mark_auto_message_sent(OTHER_CH, 2, now - 999 * 60)
    due = await bot_other._due_auto_message(OTHER_CH)
    check(due is None or due["text"] != "выключено",
          "выключенное сообщение не отправляется, как бы ни было просрочено")

    print("\n[10] Границы держит бэкенд, а не только страница")
    many = [{"text": f"msg{i}", "interval_min": 20} for i in range(30)]
    saved = await db.set_channel_auto_messages(OTHER_CH, many)
    check(len(saved) <= db.AUTO_MSG_MAX_COUNT,
          f"больше {db.AUTO_MSG_MAX_COUNT} сообщений не сохраняется ({len(saved)})")

    saved = await db.set_channel_auto_messages(OTHER_CH, [
        {"text": "x" * 5000, "interval_min": 1},
    ])
    check(len(saved[0]["text"]) <= db.AUTO_MSG_MAX_LEN,
          f"длина обрезана до {db.AUTO_MSG_MAX_LEN} ({len(saved[0]['text'])})")
    check(saved[0]["interval_min"] in db.AUTO_MSG_INTERVALS,
          f"недопустимый интервал 1 мин приведён к разрешённому "
          f"({saved[0]['interval_min']}) — иначе бот спамил бы чат")

    print("\n[11] Правка одного сообщения не сбивает расписание остальных")
    await db.set_channel_auto_messages(OTHER_CH, [
        {"text": "стабильное", "interval_min": 30},
        {"text": "меняемое", "interval_min": 30},
    ])
    stamp = _t.time() - 5 * 60
    await db.mark_auto_message_sent(OTHER_CH, 0, stamp)
    await db.set_channel_auto_messages(OTHER_CH, [
        {"text": "стабильное", "interval_min": 30},
        {"text": "меняемое", "interval_min": 60},
    ])
    rows = await db.get_channel_auto_messages(OTHER_CH)
    keep = next(r for r in rows if r["text"] == "стабильное")
    check(keep["last_sent_at"] is not None and abs(keep["last_sent_at"] - stamp) < 1,
          "отсчёт нетронутой строки сохранился — после сохранения не будет пачки")

    print("\n[12] Чужой эфир не анонсируется в Telegram владельца")
    # Telegram в конфиге ОДИН на платформу, а функция зовётся для любого
    # вышедшего в эфир канала. Без гейта аудитория владельца получала бы
    # анонсы чужих стримов.
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

    real_session = notifications.aiohttp.ClientSession
    notifications.aiohttp.ClientSession = _StubSession
    try:
        await notifications.notify_stream_online(OTHER_CH, "otherstreamer")
        check(not posted, f"эфир чужого канала в Telegram НЕ ушёл (запросов: {len(posted)})")
    finally:
        notifications.aiohttp.ClientSession = real_session
        for key in ("TELEGRAM_NOTIFICATIONS_ENABLED", "TELEGRAM_BOT_TOKEN",
                    "TELEGRAM_CHAT_ID", "TELEGRAM_NOTIFY_CHANNEL_ID"):
            os.environ.pop(key, None)

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
