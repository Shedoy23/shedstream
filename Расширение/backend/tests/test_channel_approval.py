# -*- coding: utf-8 -*-
"""Ворота для стримеров: зарегистрировался ≠ работает.

Регистрация самообслуживаемая: зашёл на /streamer, вошёл через Twitch — и канал
в реестре. Пока расширение не опубликовано, это безопасно: чужие о нём не знают.
В день одобрения Twitch «безвестность» исчезает разом, и любой стример пойдёт по
пути установки мода, который никто ни разу не проходил чужими руками. Владелец
работает соло — каждый неподготовленный стример это вечер переписки вместо
разработки.

Самое опасное в этой правке — умолчания. Ошибка в одну сторону закрывает канал
владельца на живом стриме; в другую — молча пускает кого угодно. Тест проверяет
обе.

Запуск:  python tests/test_channel_approval.py
"""
import asyncio
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

for _k, _v in (("TWITCH_OAUTH_TOKEN", "x"), ("TWITCH_CLIENT_ID", "x"),
               ("TWITCH_CLIENT_SECRET", "x"), ("TWITCH_BOT_ID", "x"),
               ("TWITCH_BROADCASTER_ID", "98319857")):
    os.environ.setdefault(_k, _v)

OWNER = 98319857          # канал владельца — существовал ДО миграции
NEWCOMER = 555000222      # чужой стример, зарегистрировался сам

passed = 0
failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print("  OK   %s" % msg)
    else:
        failed += 1
        print("  FAIL %s" % msg)


async def main():
    import aiosqlite
    import database as database_mod
    import dependencies as deps
    from migrations import m1_multitenant, m99_channel_approval

    path = os.path.join(tempfile.mkdtemp(prefix="approval_"), "t.db")
    db = database_mod.Database(path)
    await db.init_tables()
    async with aiosqlite.connect(path) as c:
        await m1_multitenant.apply(c)
        await c.commit()
    await db.init_tables()

    # Канал владельца существует ДО миграции — как на проде.
    await db.upsert_channel(channel_id=OWNER, login="shedoy23",
                            display_name="Shedoy23")

    async with aiosqlite.connect(path) as c:
        await m99_channel_approval.apply(c)

    # ── 1. Миграция не должна закрыть того, кто уже работал ────────────────
    rows = {r["channel_id"]: r for r in await db.list_channels()}
    check(rows.get(OWNER, {}).get("approved") is True,
          "СУЩЕСТВОВАВШИЙ канал остался одобрен — владелец не закрыл сам себя")

    await deps.init_registered_channels_cache(db)
    check(deps.is_channel_approved(OWNER),
          "и в кэше он одобрен (проверка доступа его пропустит)")

    # ── 2. Новый канал приходит ОЖИДАЮЩИМ ──────────────────────────────────
    await db.upsert_channel(channel_id=NEWCOMER, login="newstreamer",
                            display_name="NewStreamer")
    await deps.init_registered_channels_cache(db)

    check(deps.is_channel_registered(NEWCOMER),
          "новый канал ЗАРЕГИСТРИРОВАН (заявка принята, это не «канала нет»)")
    check(not deps.is_channel_approved(NEWCOMER),
          "но НЕ одобрен: умолчание безопасное — забыл одобрить, человек ждёт; "
          "ошибись мы наоборот, зашёл бы кто угодно")

    # ── 3. Два состояния различимы, и это важно ────────────────────────────
    # Зрителю незарегистрированного канала надо звать стримера; зрителю
    # ожидающего звать некого — заявка уже подана. Один текст на оба состояния
    # заставил бы стримера регистрироваться повторно.
    from fastapi import HTTPException
    codes = {}
    for cid, key in ((999999999, "not_registered"), (NEWCOMER, "pending")):
        try:
            if not deps.is_channel_registered(cid):
                deps._raise_channel_not_registered(cid)
            if not deps.is_channel_approved(cid):
                deps._raise_channel_pending(cid)
            codes[key] = "пропущен"
        except HTTPException as e:
            codes[key] = e.detail.get("status")
    check(codes["not_registered"] == "channel_not_registered",
          "незнакомый канал → «стример не подключил расширение»")
    check(codes["pending"] == "channel_pending_approval",
          "ожидающий канал → ОТДЕЛЬНЫЙ ответ «заявка ждёт», а не тот же самый")

    # ── 4. Одобрение действует без рестарта ────────────────────────────────
    ok = await db.set_channel_approved(NEWCOMER, True)
    deps.mark_channel_approved(NEWCOMER, True)
    check(ok and deps.is_channel_approved(NEWCOMER),
          "после одобрения канал работает СРАЗУ — рестарт прода посреди стрима "
          "рвёт зрителям соединение, поэтому он недопустим")

    # ── 5. Одобрение можно отозвать ────────────────────────────────────────
    await db.set_channel_approved(NEWCOMER, False)
    deps.mark_channel_approved(NEWCOMER, False)
    check(not deps.is_channel_approved(NEWCOMER),
          "одобрение отзывается (нужно, если канал начнёт злоупотреблять)")

    # ── 6. Несуществующий канал одобрить нельзя ────────────────────────────
    check(await db.set_channel_approved(123456789, True) is False,
          "одобрение несуществующего канала честно возвращает «не найден»")

    if getattr(db, "_pool", None):
        await db._pool.close()

    print("=" * 70)
    print("PASSED: %d   FAILED: %d" % (passed, failed))
    print("ALL GREEN — ворота стоят, владелец не заперт снаружи." if not failed
          else "КРАСНО — ворота работают неверно.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
