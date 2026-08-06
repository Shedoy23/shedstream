"""
test_first_step_card.py — карточка первого шага и подписи под кнопками.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_first_step_card.py

ПОЧЕМУ ИМЕННО ЭТО ПОКРЫТО. Здесь проверяются утверждения, которые я СЛОВАМИ
сказал владельцу, а машина их не подтверждала:

  • «у кого персонаж есть — приглашения не будет, будет переход»;
  • «после гибели героя в Bannerlord приглашение вернётся, а в RimWorld нет,
    потому что там пешку ВОСКРЕШАЮТ, а не создают заново» — три игры, три
    разных правила, и различие держалось только на моём объяснении;
  • «когда игра у стримера не запущена, карточка честно пишет об этом, но
    кнопку НЕ гасит» — первую версию я как раз сделал с гашением, и это
    выглядело бы сломанным расширением для ревьюера Twitch;
  • «подписи Семья/Гильдия показывают правду» — до 05.08 они были зашиты
    в разметку намертво: женатый читал «Свободен», состоящий в гильдии —
    «Не состоишь». Данные существовали, их просто никто не подставлял.

Класс ошибки, который ловят эти проверки: **нарисовано состояние, которого
никто не считает**. Он всплывал в проекте уже не раз и виден только глазами
на живом экране — то есть случайно.
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
USER = "viewer_one"

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


async def _clear(db, table: str):
    async with db._connect() as conn:
        await conn.execute(f"DELETE FROM {table} WHERE channel_id=?", (CHANNEL_ID,))
        await conn.commit()


async def run() -> None:
    import dependencies
    import module_liveness
    from database import Database
    # m1 добавляет channel_id легаси-таблицам (marriages завели ещё
    # одноканальной) — без неё подписи молча остаются пустыми.
    from migrations import (m1_multitenant, m11_guilds, m14_bannerlord,
                            m83_shedcolony, m109_module_last_seen)
    from routes.viewer import (_first_step_for, _card_subtitles,
                               _FIRST_STEP as FIRST_STEP_SPECS)

    tmp = tempfile.mkdtemp(prefix="first-step-")
    db = Database(os.path.join(tmp, "test.db"))
    dependencies.set_db(db)
    await db.init_pool()
    await db.init_tables()
    async with db._connect() as conn:
        for m in (m1_multitenant, m11_guilds, m14_bannerlord, m83_shedcolony,
                  m109_module_last_seen):
            await m.apply(conn)
        await conn.execute(
            "INSERT OR IGNORE INTO channels (channel_id, login, display_name, tier) "
            "VALUES (?, 'test_chan', 'Test', 'free')", (CHANNEL_ID,))
        await conn.commit()

    try:
        print("\n[1] модуль не подключён — карточки нет вообще")
        check(await _first_step_for(db, CHANNEL_ID, USER, None), None,
              "без активной игры карточка не показывается")
        check(await _first_step_for(db, CHANNEL_ID, USER, "чего-то-нет"), None,
              "незнакомая игра карточку не создаёт")

        print("\n[2] Bannerlord: героя нет — приглашение, кнопка бесплатная")
        step = await _first_step_for(db, CHANNEL_ID, USER, "bannerlord")
        check(bool(step), True, "приглашение показано")
        check(step["compact"], False, "приглашение — большая карточка, не строка")
        check(step["price"], 0, "создание героя бесплатное")
        check(step["cta"], "Начать играть", "кнопка называет результат, а не механику")
        check(step["enabled"], True, "кнопка рабочая")

        print("\n[3] Bannerlord: герой есть — переход вместо приглашения")
        async with db._connect() as conn:
            await conn.execute(
                "INSERT INTO bannerlord_heroes (channel_id, username, hero_id, "
                "display_name, is_alive) VALUES (?,?,?,?,1)",
                (CHANNEL_ID, USER, "hero_1", "Эдвард Храбрый"))
            await conn.commit()
        step = await _first_step_for(db, CHANNEL_ID, USER, "bannerlord")
        check(step["compact"], True, "у кого герой есть — короткая строка")
        check(step["title"], "Твой герой · Эдвард Храбрый", "в строке имя героя")
        check(step["cta"], "Открыть", "кнопка ведёт на вкладку")
        check(step["text"], "", "приглашения в тексте нет — оно было бы враньём")

        print("\n[4] Bannerlord: герой погиб — приглашение ВОЗВРАЩАЕТСЯ")
        # Здесь после гибели нужен НОВЫЙ герой (наследник/возрождение).
        async with db._connect() as conn:
            await conn.execute(
                "UPDATE bannerlord_heroes SET is_alive=0 WHERE channel_id=? AND username=?",
                (CHANNEL_ID, USER))
            await conn.commit()
        step = await _first_step_for(db, CHANNEL_ID, USER, "bannerlord")
        check(step["compact"], False, "мёртвый герой → снова приглашение завести")

        print("\n[5] RimWorld: мёртвая пешка — приглашения НЕТ")
        # Отличие от Bannerlord намеренное: пешку ВОСКРЕШАЮТ, она никуда не
        # делась, и звать заводить новую — сбивать зрителя с толку.
        async with db._connect() as conn:
            await conn.execute(
                "INSERT INTO rimworld_pawns (channel_id, username, pawn_name, is_alive) "
                "VALUES (?,?,?,0)", (CHANNEL_ID, USER, "Пешка"))
            await conn.commit()
        step = await _first_step_for(db, CHANNEL_ID, USER, "rimworld")
        check(step["compact"], True, "мёртвая пешка — это всё ещё «твой персонаж»")

        print("\n[6] RimWorld: персонажа нет — цена стоит на кнопке")
        await _clear(db, "rimworld_pawns")
        step = await _first_step_for(db, CHANNEL_ID, USER, "rimworld")
        check(step["price"] > 0, True, "создание пешки платное")
        check(str(step["price"]) in step["cta"], True,
              f"цена написана на кнопке ({step['cta']!r}) — платный шаг не удивляет после нажатия")

        print("\n[7] игра не запущена — текст честный, но кнопка РАБОЧАЯ")
        # Гасить кнопку нельзя: карточка ничего не покупает, она открывает
        # вкладку. Погашенная кнопка выглядит сломанным расширением, в том
        # числе для ревьюера Twitch, если игра в этот момент закрыта.
        await _clear(db, "bannerlord_heroes")
        async with db._connect() as conn:
            await conn.execute(
                "INSERT INTO module_last_seen (channel_id, module_id, last_seen_ts) "
                "VALUES (?, 'bannerlord', ?)",
                (CHANNEL_ID, 1.0))   # сигнал из глубокого прошлого = молчит
            await conn.commit()
        module_liveness._cache.clear()
        step = await _first_step_for(db, CHANNEL_ID, USER, "bannerlord")
        check(step["enabled"], True, "кнопка не гасится — расширение остаётся проходимым")
        # Проверяем СМЫСЛ, а не конкретные слова: тексты живут на бэкенде
        # ровно затем, чтобы их можно было переписать без ревью Twitch, и
        # тест, придирающийся к формулировке, сломается на первой же правке
        # копирайта. (Первая версия этой проверки искала слово, которого в
        # тексте нет, и падала на исправном коде.)
        check(step["cta"], "Посмотреть", "кнопка зовёт посмотреть, а не «начать играть»")
        check(step["text"] != FIRST_STEP_SPECS["bannerlord"]["text"], True,
              "текст офлайна отличается от обычного приглашения")
        check(step["price"], 0, "цену при выключенной игре не показываем")

        print("\n[8] подписи под кнопками показывают правду")
        subs = await _card_subtitles(db, CHANNEL_ID, USER)
        check(subs.get("family-status-desc"), "Свободен", "холост → «Свободен»")
        check(subs.get("guild-state"), "Не состоишь", "без гильдии → «Не состоишь»")

        async with db._connect() as conn:
            await conn.execute(
                "INSERT INTO marriages (channel_id, user1, user2) VALUES (?,?,?)",
                (CHANNEL_ID, USER, "spouse_two"))
            await conn.execute(
                "INSERT INTO guilds (channel_id, name, master_username) VALUES (?,?,?)",
                (CHANNEL_ID, "Орден Кристалла", USER))
            cur = await conn.execute("SELECT id FROM guilds WHERE channel_id=?", (CHANNEL_ID,))
            gid = (await cur.fetchone())[0]
            await conn.execute(
                "INSERT INTO guild_members (channel_id, guild_id, username, role) "
                "VALUES (?,?,?,'master')", (CHANNEL_ID, gid, USER))
            await conn.commit()

        subs = await _card_subtitles(db, CHANNEL_ID, USER)
        check(subs.get("family-status-desc"), "В браке · @spouse_two",
              "женатый видит партнёра, а не «Свободен» (до 05.08 врало всем)")
        check(subs.get("guild-state"), "Орден Кристалла",
              "состоящий видит гильдию, а не «Не состоишь»")
    finally:
        await db._pool.close()

    print("\n" + "=" * 70)
    print(f"PASSED: {len(_successes)}   FAILED: {len(_failures)}")
    if _failures:
        print("ЕСТЬ ПРОВАЛЫ:")
        for f in _failures:
            print(f)
    else:
        print("ALL GREEN ✅ — карточка и подписи отражают настоящее состояние.")


def main() -> int:
    try:
        asyncio.run(run())
    except Exception:
        traceback.print_exc()
        return 1
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
