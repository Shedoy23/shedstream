"""
test_stream_session_single.py — один эфир = одна сессия, серия не обнуляется.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_stream_session_single.py

ПОВОД (владелец, 06.08: «почему стрики сбрасываются»). Сессию стрима писали два
независимых места: EventSub — настоящим id стрима от Twitch, опросчик Helix —
СЕГОДНЯШНЕЙ ДАТОЙ. На каждый эфир получалось две строки: короткий огрызок с
нулём зрителей и настоящая многочасовая сессия.

Серия «N стримов подряд» считается как «сколько сессий началось между прошлой
посещённой и этой». Фантом попадал в этот счёт как ПРОПУЩЕННЫЙ стрим — и серия
обнулялась после каждого эфира. В боевой базе: у всех `current_streak = 1` при
5–15 посещённых стримах, ни одного достижения за серию за всю историю проекта
(для первого нужно три подряд).

Сценарии:
  1. Helix дал id → сессия заводится под ним (а не под датой) — это сам фикс;
  2. Helix id не дал → падаем обратно на дату, поведение не хуже прежнего;
  3. стрим кончился → запомненный id забывается, чтобы не приклеиться
     к следующему эфиру;
  4. два писателя с ОДНИМ id дают ОДНУ строку сессии (идемпотентность);
  5. два писателя с РАЗНЫМИ id дают две строки — воспроизведение самой поломки,
     ради которой всё и затевалось.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import traceback
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
os.environ.setdefault("TWITCH_BROADCASTER_ID", "98319857")

CHANNEL_ID = 98319857
REAL_STREAM_ID = "316642260564"
TODAY_ID = "2026-08-06"

_failures: list = []
_successes: list = []


def check(actual, expected, label: str):
    if actual == expected:
        _successes.append(label)
        print(f"  ✅ {label}")
    else:
        msg = f"  ❌ {label}: ожидалось {expected!r}, получено {actual!r}"
        _failures.append(msg)
        print(msg)


async def _session_count(db) -> int:
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM stream_sessions WHERE channel_id=?", (CHANNEL_ID,))
        return (await cur.fetchone())[0]


async def run() -> None:
    import dependencies
    from database import Database
    from bot_core import BotCore

    tmp = tempfile.mkdtemp(prefix="stream-session-")
    db = Database(os.path.join(tmp, "test.db"))
    dependencies.set_db(db)
    await db.init_pool()
    await db.init_tables()

    bot = BotCore(db)
    try:
        print("\n[1] Helix отдал настоящий id стрима")
        bot._stream_ext_id[CHANNEL_ID] = REAL_STREAM_ID
        check(bot._session_id_for(CHANNEL_ID, TODAY_ID), REAL_STREAM_ID,
              "сессия заводится под настоящим id, а не под датой (это и есть фикс)")

        print("\n[2] Helix id не отдал")
        bot._stream_ext_id.pop(CHANNEL_ID, None)
        check(bot._session_id_for(CHANNEL_ID, TODAY_ID), TODAY_ID,
              "без id от Twitch падаем обратно на дату")

        print("\n[3] стрим закончился — id не должен приклеиться к следующему")
        bot._stream_ext_id[CHANNEL_ID] = REAL_STREAM_ID
        bot._stream_ext_id.pop(CHANNEL_ID, None)   # то же делает опросчик на офлайне
        check(bot._session_id_for(CHANNEL_ID, TODAY_ID), TODAY_ID,
              "после эфира возвращаемся к дате")

        print("\n[4] два писателя с ОДНИМ id → одна сессия")
        await db.register_stream_session(REAL_STREAM_ID, channel_id=CHANNEL_ID)
        await db.register_stream_session(REAL_STREAM_ID, channel_id=CHANNEL_ID)
        check(await _session_count(db), 1, "повторная регистрация не плодит строку")

        print("\n[5] два писателя с РАЗНЫМИ id → две сессии (это была поломка)")
        await db.register_stream_session(TODAY_ID, channel_id=CHANNEL_ID)
        check(await _session_count(db), 2,
              "разные id дают лишнюю сессию — ровно она и обнуляла серии")
    finally:
        await db._pool.close()

    print("\n" + "=" * 70)
    print(f"PASSED: {len(_successes)}   FAILED: {len(_failures)}")
    if _failures:
        print("ЕСТЬ ПРОВАЛЫ — один эфир по-прежнему даёт две сессии:")
        for f in _failures:
            print(f)
    else:
        print("ALL GREEN ✅ — эфир пишется одной сессией, фантом не появляется.")


def main() -> int:
    try:
        asyncio.run(run())
    except Exception:
        traceback.print_exc()
        return 1
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
