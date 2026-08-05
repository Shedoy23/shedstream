"""
test_voting_timer.py — автозакрытие голосования и обратный отсчёт у зрителя.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_voting_timer.py

ПОВОД (2026-08-05, владелец: «у голосования за игру не работает таймер
автоокончания»). Нашлись ДВЕ независимые поломки одного корня — время
голосования писалось как «голый» UTC без пометки, и два потребителя поняли
его по-разному:

  1. Сервер сравнивал `ends_at <= CURRENT_TIMESTAMP` СТРОКАМИ. Питон писал
     `2026-08-05T09:00:00.123456` (через «T»), SQLite отдаёт
     `2026-08-05 11:49:19` (через пробел). На одной и той же дате «T» (0x54)
     больше пробела (0x20), поэтому истёкшее голосование НЕ находилось —
     до тех пор, пока не сменится дата по UTC. То есть автозакрытие
     срабатывало только после полуночи.

  2. Браузер зрителя делал `new Date("2026-08-05T09:00:00.123456")`. По
     стандарту строка без часового пояса читается как МЕСТНОЕ время. Бэкенд
     писал UTC, зритель из Москвы (UTC+3) получал время на 3 часа раньше
     нужного — отсчёт показывал 00:00 с первой секунды.

Оба сценария ниже падают на старом коде и проходят на новом. Красным их
видели: см. коммит с фиксом.

Сценарии:
  1. голосование, истёкшее СЕГОДНЯ, попадает в выборку автозакрытия;
  2. ещё не истёкшее — не попадает;
  3. истёкшее ВЧЕРА — попадает (эту ветку старый код проходил случайно);
  4. `ends_at`, отданное клиенту, помечено как UTC — браузер прочитает его
     одинаково в любом часовом поясе.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import traceback
from datetime import datetime, timedelta
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


async def _insert_event(db, ends_at: str) -> int:
    """Положить активное голосование с заданным сроком (формат — как у прода:
    naive-UTC ISO через «T», ровно то, что пишет `datetime.utcnow().isoformat()`)."""
    async with db._connect() as conn:
        await conn.execute("DELETE FROM voting_events WHERE channel_id = ?", (CHANNEL_ID,))
        cur = await conn.execute(
            "INSERT INTO voting_events (channel_id, template_name, ends_at, status) "
            "VALUES (?, ?, ?, 'active')",
            (CHANNEL_ID, "Тестовое голосование", ends_at),
        )
        await conn.commit()
        return cur.lastrowid


async def run() -> None:
    import dependencies
    from database import Database

    # Таблицы голосования приезжают миграцией m12, а не init_tables. Берём
    # именно её, чтобы схема в тесте была той же, что на проде, а не копией
    # DDL, которая разъедется при следующей миграции.
    from migrations import m12_voting, m88_game_vote_proposals

    tmp = tempfile.mkdtemp(prefix="voting-timer-")
    db = Database(os.path.join(tmp, "test.db"))
    dependencies.set_db(db)
    await db.init_pool()
    await db.init_tables()

    async with db._connect() as conn:
        await m12_voting.apply(conn)
        await m88_game_vote_proposals.apply(conn)
        await conn.execute(
            "INSERT OR IGNORE INTO channels (channel_id, login, display_name, tier) "
            "VALUES (?, 'test_chan', 'Test Channel', 'free')",
            (CHANNEL_ID,),
        )
        await conn.commit()

    now = datetime.utcnow()

    print("\n[1] голосование истекло СЕГОДНЯ (два часа назад)")
    await _insert_event(db, (now - timedelta(hours=2)).isoformat())
    expired = await db.find_expired_voting_events()
    check(len(expired), 1, "истёкшее сегодня найдено автозакрытием")

    print("\n[2] голосование ЕЩЁ идёт (закончится через два часа)")
    await _insert_event(db, (now + timedelta(hours=2)).isoformat())
    expired = await db.find_expired_voting_events()
    check(len(expired), 0, "действующее голосование не закрывается досрочно")

    print("\n[3] голосование истекло ВЧЕРА")
    await _insert_event(db, (now - timedelta(days=1)).isoformat())
    expired = await db.find_expired_voting_events()
    check(len(expired), 1, "вчерашнее истёкшее найдено")

    print("\n[4] срок, отданный зрителю, помечен как UTC")
    await _insert_event(db, (now + timedelta(minutes=5)).isoformat())
    event = await db.get_active_voting_event(CHANNEL_ID)
    ends_at = (event or {}).get("ends_at") or ""
    check(
        ends_at.endswith("Z") or "+" in ends_at[10:],
        True,
        f"ends_at={ends_at!r} читается браузером как UTC, а не как местное время",
    )

    # Пул закрываем явно: иначе процесс не завершается и прогон выглядит как
    # зависание, а код возврата приходит от таймаута, а не от теста.
    await db._pool.close()

    print("\n" + "=" * 70)
    print(f"PASSED: {len(_successes)}   FAILED: {len(_failures)}")
    if _failures:
        print("ЕСТЬ ПРОВАЛЫ — таймер голосования не чинён:")
        for f in _failures:
            print(f)
    else:
        print("ALL GREEN ✅ — автозакрытие срабатывает в тот же день, "
              "отсчёт у зрителя честный.")


def main() -> int:
    try:
        asyncio.run(run())
    except Exception:
        traceback.print_exc()
        return 1
    # Код возврата — единственный судья прогона. Печать «ALL GREEN» без нуля
    # здесь ничего не значит (класс ошибки: зелёный вывод ≠ зелёный результат).
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
