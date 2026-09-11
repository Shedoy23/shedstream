"""
test_rimworld_game_offline_gate.py — платное действие RimWorld не списывает
деньги, когда игра не запущена.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_rimworld_game_offline_gate.py

ЧТО ДОКАЗЫВАЕТ (постстрим-триаж 2026-09-11).
    На эфире 10.09 RimWorld не был запущен, но «создать пешку» (200💎) прошло
    дважды, «вылечить» (150💎) — один раз. Зритель видел «✨ Пешка создаётся!»,
    деньги списались, команда легла в очередь, которую некому было вычерпать.
    Обработчики не проверяли, на связи ли игра, — хотя бэкенд знал ответ:
    панель в те же минуты 1011 раз получила от него `online: false`.

    Хуже того, на проде стоит RIMWORLD_REQUIRE_STREAM_LIVE=false (тех-режим), и
    старая проверка при нём выходила сразу — не проверялся даже эфир. Платное
    действие RimWorld проходило в любой момент суток. Случай [6] — ровно эта
    конфигурация.

    Проверяется исполнением настоящих обработчиков `create_pawn` и `heal_pawn`.

ЧТО ЗДЕСЬ ПОДМЕНЕНО. Распознавание эфира (`bot._is_stream_live` → «идёт») и
Twitch JWT — они не предмет теста, их держат свои гейты. Подмена JWT делает то
же, что настоящий `require_jwt_user`: кладёт канал в контекст запроса, — иначе
касса, читающая канал оттуда, падала бы на пустом месте. Метка «игра на связи»
НЕ подменяется функцией: она пишется в тот же кэш module_liveness, что
заполняет пульс мода.

ТЕСТЫ:
    [1] игра ни разу не выходила на связь → отказ, деньги целы, очередь пуста
    [2] игра молчит 20 минут → отказ
    [3] отказ — в той же форме, что прочие отказы: замороженная панель его покажет
    [4] лечение при выключенной игре тоже отказано — гейт общий, а не у одной кнопки
    [5] игра была на связи 10 секунд назад → покупка проходит и списывает
    [6] тех-режим прода (эфир не проверяется) — игру всё равно проверяет
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass

HERE = Path(__file__).parent.absolute()
sys.path.insert(0, str(HERE.parent))

for _v, _d in (("TWITCH_OAUTH_TOKEN", "oauth:test"), ("TWITCH_CLIENT_ID", "c"),
               ("TWITCH_CLIENT_SECRET", "s"), ("TWITCH_BOT_ID", "b"),
               ("TWITCH_CHANNEL_NAME", "ch"),
               ("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab"),
               ("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890"),
               ("ADMIN_PASSWORD", "test_admin_password_for_tests_only"),
               ("TWITCH_BROADCASTER_ID", "98319857")):
    os.environ.setdefault(_v, _d)

CH = 98319857
USER = "laitru"
OTHER = "ethanenok"
START = 10000

_failures: list = []


def check(label: str, ok: bool, detail: str = ""):
    if ok:
        print(f"  OK  {label}")
    else:
        msg = f"  FAIL {label}" + (f" — {detail}" if detail else "")
        _failures.append(msg)
        print(msg)


class _LiveBot:
    async def _is_stream_live(self, channel_id=None):
        return True


class _Req:
    """Обработчику нужен только объект запроса — JWT подменён ниже."""


def _as_viewer(rimworld, user):
    """Подмена JWT, верная проду.

    Настоящие `require_jwt_user` / `require_jwt_channel` не только возвращают
    зрителя и канал, но и кладут канал в контекст запроса; касса дальше читает
    его оттуда (`db.get_points(username)` без канала). Без этого подмена
    воспроизводила бы не прод, а падение на пустом месте.
    """
    import dependencies

    def _user(_r):
        dependencies.set_request_channel_id(CH)
        return (user, CH)

    def _channel(_r):
        dependencies.set_request_channel_id(CH)
        return CH

    rimworld.require_jwt_user = _user
    rimworld.require_jwt_channel = _channel


async def _points(db, user=USER):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT points FROM viewers WHERE channel_id=? AND username=?", (CH, user))
        row = await cur.fetchone()
    return row[0] if row else None


async def _queued(db):
    """Всё, что касса поставила в очередь, — в обеих очередях."""
    n = 0
    async with db._connect() as conn:
        for sql in ("SELECT COUNT(*) FROM module_actions WHERE channel_id=?",
                    "SELECT COUNT(*) FROM rimworld_pending_commands WHERE channel_id=?"):
            try:
                cur = await conn.execute(sql, (CH,))
                n += (await cur.fetchone())[0]
            except Exception:
                pass            # таблицы старой очереди может ещё не быть
    return n


def _game_seen(seconds_ago):
    import module_liveness
    module_liveness._cache.pop((CH, "rimworld"), None)
    if seconds_ago is not None:
        module_liveness._cache[(CH, "rimworld")] = time.time() - seconds_ago


async def _build_db(db_path: str):
    import main
    import dependencies
    from database import Database

    test_db = Database(db_path)
    main.db = test_db
    dependencies.set_db(test_db)
    await test_db.init_pool()
    await test_db.init_tables()
    await main.run_migrations()
    async with test_db._connect() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO channels (channel_id, login, display_name, tier) "
            "VALUES (?, 'shedoy23', 'shedoy23', 'free')", (CH,))
        for user in (USER, OTHER):
            await conn.execute(
                "INSERT OR IGNORE INTO viewers (channel_id, username, points) "
                "VALUES (?, ?, ?)", (CH, user, START))
        await conn.commit()
    return test_db


async def run():
    db_path = tempfile.mktemp(suffix="_rw_gate.db")
    db = await _build_db(db_path)
    try:
        import config
        import main
        import rimworld

        config.TESTING_BYPASS_STREAM_LIVE = False
        config.RIMWORLD_REQUIRE_STREAM_LIVE = True
        main.bot = _LiveBot()                                   # см. шапку
        _as_viewer(rimworld, USER)

        print("\n[1] Игра ни разу не выходила на связь")
        _game_seen(None)
        resp = await rimworld.create_pawn(_Req())
        check("создание пешки отказано", resp.get("success") is False,
              f"ответ: {resp}")
        check("деньги целы", await _points(db) == START,
              f"баланс {await _points(db)} — игра не запущена, а деньги списаны "
              f"(продовый симптом 10.09)")
        check("в очередь ничего не легло", await _queued(db) == 0,
              f"в очередях: {await _queued(db)}")

        print("\n[2] Игра молчит 20 минут")
        _game_seen(20 * 60)
        resp = await rimworld.create_pawn(_Req())
        check("отказано", resp.get("success") is False, f"ответ: {resp}")
        check("деньги целы", await _points(db) == START, f"баланс {await _points(db)}")

        print("\n[3] Форма отказа")
        msg = str(resp.get("message") or "")
        check("отказ несёт человеческую причину про игру",
              "игра" in msg.lower() and len(msg) > 20, f"сообщение: {msg!r}")

        print("\n[4] Лечение при выключенной игре")
        resp = await rimworld.heal_pawn(_Req())
        check("лечение отказано", resp.get("success") is False, f"ответ: {resp}")
        check("деньги целы", await _points(db) == START, f"баланс {await _points(db)}")

        print("\n[5] Игра на связи")
        _game_seen(10)
        bal = await _points(db)
        resp = await rimworld.create_pawn(_Req())
        check("покупка прошла", resp.get("success") is True, f"ответ: {resp}")
        check("списано ровно 200", await _points(db) == bal - 200,
              f"было {bal}, стало {await _points(db)}")

        print("\n[6] Тех-режим прода: эфир не проверяется, игра — всё равно")
        # Другой зритель: у кассы защита от двойного клика по содержимому
        # команды, и повтор от того же зрителя в пределах 3 секунд она бы
        # тихо свела к уже купленному — отказ гейта был бы не виден.
        config.RIMWORLD_REQUIRE_STREAM_LIVE = False                # так на проде
        _as_viewer(rimworld, OTHER)
        _game_seen(None)
        resp = await rimworld.create_pawn(_Req())
        check("при выключенной игре отказано и в тех-режиме",
              resp.get("success") is False,
              f"ответ: {resp} — на проде RIMWORLD_REQUIRE_STREAM_LIVE=false, и без "
              f"проверки игры платное действие проходит в любой момент")
        check("деньги целы", await _points(db, OTHER) == START,
              f"баланс {OTHER} {await _points(db, OTHER)}")
    finally:
        try:
            await db._pool.close()
        except Exception:
            pass
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(db_path + suffix)
            except OSError:
                pass


def main_() -> int:
    try:
        asyncio.run(run())
    except Exception:
        traceback.print_exc()
        return 1
    print()
    if _failures:
        print(f"ПРОВАЛЕНО: {len(_failures)}")
        for f in _failures:
            print(" ", f.strip())
        return 1
    print("ВСЁ ЗЕЛЁНОЕ")
    return 0


if __name__ == "__main__":
    sys.exit(main_())
