# -*- coding: utf-8 -*-
"""Дашборд стримера показывает состояние ВЫБРАННОЙ игры, а не соседней.

ЗАЧЕМ. Две строки чеклиста врали, и по-разному:

  «Мод на связи прямо сейчас» бралось из памяти процесса модуля. После каждого
  перезапуска бэкенда там пусто, и исправно работающему стримеру дашборд писал
  «мод молчит» — человек шёл чинить то, что не сломано.

  «Мод хоть раз выходил на связь» считалось по числу героев Bannerlord,
  независимо от выбранной игры. У стримера на RimWorld галочка стояла потому,
  что когда-то играли в Bannerlord. Найдено 2026-08-20 на живой базе: активный
  модуль `rimworld`, отметок связи RimWorld нет вовсе, а галочка стояла — из-за
  шестнадцати чужих героев.

Класс ошибки: одно число отвечает на два разных вопроса. Оба вопроса теперь
задаются одной таблице `module_last_seen`, которая заведена именно для этого и
переживает перезапуск.

Запуск: python tests/test_streamer_dashboard_status.py  (судить по коду возврата)
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

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

_fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_dashboard_")
os.close(_fd)
os.unlink(db_path)
os.environ["DB_PATH"] = db_path

CHANNEL_ID = 98319857

passed = 0
failed = 0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print("  OK   " + message)
    else:
        failed += 1
        print("  FAIL " + message)


def step(result, key):
    for s in result["steps"]:
        if s["key"] == key:
            return s
    raise AssertionError("нет шага %s" % key)


async def set_last_seen(db, module_id, age_seconds):
    async with db._connect() as conn:
        await conn.execute(
            "INSERT INTO module_last_seen (channel_id, module_id, last_seen_ts) "
            "VALUES (?,?,?) ON CONFLICT(channel_id, module_id) "
            "DO UPDATE SET last_seen_ts=excluded.last_seen_ts",
            (CHANNEL_ID, module_id, time.time() - age_seconds))
        await conn.commit()


async def set_module(db, module_id):
    async with db._connect() as conn:
        await conn.execute("UPDATE channels SET active_module=? WHERE channel_id=?",
                           (module_id, CHANNEL_ID))
        await conn.commit()


def fake_request():
    """Минимальный Request: эндпоинт берёт из него только session cookie,
    который мы всё равно подменяем."""
    from starlette.requests import Request

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request({
        "type": "http", "http_version": "1.1", "method": "GET", "scheme": "https",
        "path": "/api/streamer/setup-status", "raw_path": b"/api/streamer/setup-status",
        "query_string": b"", "headers": [],
        "client": ("127.0.0.1", 1), "server": ("testserver", 443),
    }, receive)


async def main() -> int:
    import dependencies
    import main as main_mod
    from database import Database
    from routes import streamer

    db = Database(db_path)
    try:
        await db.init_tables()
        await main_mod.run_migrations()
        async with db._connect() as conn:
            cols = await (await conn.execute("PRAGMA table_info(channels)")).fetchall()
            if "approved" not in {c[1] for c in cols}:
                await conn.execute(
                    "ALTER TABLE channels ADD COLUMN approved INTEGER NOT NULL DEFAULT 0")
            await conn.execute(
                "INSERT OR IGNORE INTO channels "
                "(channel_id,login,display_name,tier,approved,active_module) "
                "VALUES (?, 'alice', 'Alice', 'free', 1, 'rimworld')", (CHANNEL_ID,))
            # Шестнадцать чужих героев — ровно та ситуация, что была на проде.
            # Вставка НЕ заворачивается в try: если она молча не сработает,
            # первая проверка ниже станет зелёной по другой причине («героев и
            # так нет»), а тест — бесполезным. Первый прогон именно так и
            # обманул: колонки NOT NULL были пропущены, вставка падала, и
            # заявленное условие не воспроизводилось.
            for i in range(16):
                await conn.execute(
                    "INSERT OR IGNORE INTO bannerlord_heroes "
                    "(channel_id, username, hero_id, display_name) "
                    "VALUES (?,?,?,?)",
                    (CHANNEL_ID, "viewer%d" % i, "hero%d" % i, "Viewer %d" % i))
            await conn.commit()
            cur = await conn.execute(
                "SELECT COUNT(*) FROM bannerlord_heroes WHERE channel_id=?",
                (CHANNEL_ID,))
            heroes_in_fixture = (await cur.fetchone())[0]
        dependencies.set_db(db)
        streamer._read_session_cookie = lambda _r: CHANNEL_ID

        check(heroes_in_fixture == 16,
              "фикстура действительно содержит 16 героев Bannerlord — "
              "без этого следующая проверка зеленела бы по чужой причине")

        # ── RimWorld выбран, отметок связи RimWorld нет ──────────────────────
        result = await streamer.streamer_setup_status(fake_request())
        check(step(result, "mod_ever")["done"] is False,
              "у RimWorld без единой отметки связи галочка НЕ стоит, "
              "даже когда в базе шестнадцать героев Bannerlord")
        check(step(result, "mod_now")["done"] is False,
              "«на связи сейчас» тоже отрицательно")

        # ── Bannerlord был на связи, но выбран не он ─────────────────────────
        await set_last_seen(db, "bannerlord", 5)
        result = await streamer.streamer_setup_status(fake_request())
        check(step(result, "mod_ever")["done"] is False
              and step(result, "mod_now")["done"] is False,
              "связь СОСЕДНЕЙ игры не засчитывается выбранной")

        # ── RimWorld вышел на связь ─────────────────────────────────────────
        await set_last_seen(db, "rimworld", 5)
        result = await streamer.streamer_setup_status(fake_request())
        check(step(result, "mod_ever")["done"] and step(result, "mod_now")["done"],
              "свежая отметка выбранной игры даёт обе галочки")
        check(result["mod_online"] is True and result["mod_silent_sec"] is not None,
              "наружу отдаются и статус, и сколько секунд молчит")

        # ── Мод замолчал: «был» остаётся, «сейчас» гаснет ────────────────────
        await set_last_seen(db, "rimworld", 3600)
        result = await streamer.streamer_setup_status(fake_request())
        check(step(result, "mod_ever")["done"] is True,
              "«хоть раз выходил на связь» переживает молчание — "
              "и, в отличие от прежней памяти процесса, переживёт перезапуск")
        check(step(result, "mod_now")["done"] is False
              and "60 мин" in step(result, "mod_now")["hint"],
              "«сейчас» гаснет и подсказка называет, сколько именно молчит")

        # ── Переключились на игру, которая ни разу не выходила ───────────────
        await set_module(db, "shedcolony")
        result = await streamer.streamer_setup_status(fake_request())
        check(step(result, "mod_ever")["done"] is False,
              "смена игры сбрасывает картину: у новой игры своя история связи")

        print("=" * 70)
        print("PASSED: %d   FAILED: %d" % (passed, failed))
        print("ALL GREEN — дашборд показывает выбранную игру, а не соседнюю."
              if not failed else "КРАСНО — дашборд снова говорит не о том модуле.")
        return 1 if failed else 0
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def _run() -> int:
    try:
        return asyncio.run(main())
    except Exception:
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    code = _run()
    sys.stdout.flush()
    os._exit(code)
