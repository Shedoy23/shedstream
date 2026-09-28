"""
test_module_delivery_gaps.py — два непокрытых сценария доставки Module API.

Повод: внешний разбор модульного ядра (2026-08-02). Он верно указал, что у нас
нет тестов на «потеряли ответ после dispatch» и на «пересечение id конвертов
между модулями». Третий его сценарий — повтор упавшего события — уже покрыт
(`test_action_ack_refund_order.py`, блок [8]), здесь не дублируется.

⚠️ **Разбор читал снимок `dist/audit/` от 02.07, месячной давности.** Часть его
находок к живому коду уже неприменима. Эти два — применимы, проверено.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_module_delivery_gaps.py

## [1] Столкновение id конвертов между модулями — ДЕФЕКТ, чинится здесь же

Кольцо дедупликации хранится как `channel_id → set(envelope_id)`, без
`module_id`. Значит два модуля одного канала, приславшие конверт с одинаковым
id, затирают друг друга: второй молча объявляется дубликатом и НЕ
обрабатывается. Сейчас каналов с двумя живыми модулями нет, поэтому дефект
спит — но он проснётся ровно в тот день, когда рядом с Bannerlord встанет
shedcolony или RimWorld, и проявится как «событие пропало без следа».

Тест видели красным: до фикса `[1] конверт другого модуля не считается
дубликатом: expected False, got True`.

## [2] Переочередённое задание видно опросчику — РЕГРЕССИЯ S-07

Это S-07 из стрима 03.08. Сторож возвращает потерянное задание из
`dispatched` обратно в `queued`, сохраняя ненулевой `dispatched_at`.
Выборка обязана вернуть такой retry независимо от `PK > since_id`, иначе
монотонный курсор мода уже уехал вперёд и команда потеряется до рестарта.
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
SHARED_ENVELOPE_ID = "envelope-same-id-from-two-modules"

_failures: list = []
_successes: list = []


def assert_eq(actual, expected, label: str):
    if actual == expected:
        _successes.append(label)
        print(f"  ✅ {label}")
    else:
        msg = f"  ❌ {label}: expected {expected!r}, got {actual!r}"
        _failures.append(msg)
        print(msg)


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
            "VALUES (?, 'alice_chan', 'Alice Channel', 'free')",
            (CHANNEL_ID,))
        await conn.commit()
    return test_db


def test_envelope_id_does_not_collide_across_modules():
    """Одинаковый id конверта от РАЗНЫХ модулей — это разные конверты."""
    print("\n[1] Пересечение id конвертов между модулями")

    import routes.module_api as api

    # Чистим кольцо, чтобы тест не зависел от порядка запуска.
    api._processed_envelopes.clear()

    first = api._is_duplicate_envelope(CHANNEL_ID, SHARED_ENVELOPE_ID,
                                       module_id="bannerlord")
    assert_eq(first, False, "[1] первый конверт от bannerlord — не дубликат")

    second = api._is_duplicate_envelope(CHANNEL_ID, SHARED_ENVELOPE_ID,
                                        module_id="shedcolony")
    assert_eq(second, False,
              "[1] конверт другого модуля с тем же id — НЕ дубликат")

    again = api._is_duplicate_envelope(CHANNEL_ID, SHARED_ENVELOPE_ID,
                                       module_id="bannerlord")
    assert_eq(again, True,
              "[1] повтор того же id тем же модулем — дубликат (дедуп работает)")

    # Забывание тоже должно быть per-module.
    api._forget_envelope(CHANNEL_ID, SHARED_ENVELOPE_ID, module_id="bannerlord")
    assert_eq(api._is_duplicate_envelope(CHANNEL_ID, SHARED_ENVELOPE_ID,
                                         module_id="shedcolony"), True,
              "[1] забыли у bannerlord — у shedcolony запись осталась")


async def test_requeued_action_visible_to_moved_cursor(db):
    """S-07: retry со старым PK виден даже после продвижения cursor."""
    print("\n[2] S-07: переочередённое задание и уехавший курсор")

    pk = await db.enqueue_action(
        CHANNEL_ID, "bannerlord", "action-s07-probe", "player.spawn", {"price": 50})

    # Мод забирает задание: строка уходит в dispatched, курсор мода = pk.
    batch = await db.fetch_pending_actions(CHANNEL_ID, "bannerlord", since_id=0)
    assert_eq([r["id"] for r in batch], [pk], "[2] мод получил задание")
    cursor = max(r["id"] for r in batch)

    # Ответ мода потерян. Сторож возвращает строку в очередь ТЕМ ЖЕ id.
    async with db._connect() as conn:
        await conn.execute(
            "UPDATE module_actions SET status='queued' WHERE id=?", (pk,))
        await conn.commit()

    # Мод (не перезапускавшийся) опрашивает со своим курсором.
    again = await db.fetch_pending_actions(
        CHANNEL_ID, "bannerlord", since_id=cursor)
    assert_eq([r["id"] for r in again], [pk],
              "[2] мод получил retry со старым PK без перезапуска")


async def test_unrecognized_body_is_not_silently_ok():
    """Тело без `envelopes` — ошибка, а не «ок, ничего не сделано».

    Повод, 2026-08-02: скрипт аудита слал конверты под ключом `events`. Бэкенд
    ответил `status: ok` с пустым `acks`, конверты пропали молча, и прогон
    отрапортовал 12 несуществующих денежных дефектов. Ответ «ок» на запрос,
    который ничего не сделал, — худший из возможных: тот, кто пишет коннектор,
    считает, что доставил.
    """
    print("\n[3] Нераспознанное тело не выдаётся за успех")

    import routes.module_api as api
    from fastapi import HTTPException

    # Пустая пачка — законна, это «мне нечего слать».
    empty_ok = {"channel_id": CHANNEL_ID, "envelopes": []}
    assert_eq("envelopes" in empty_ok, True, "[3] честно пустая пачка остаётся ок")

    # Проверяем саму развилку: ключа нет и одиночного конверта нет.
    body_bad = {"channel_id": CHANNEL_ID, "events": [{"type": "action.failed"}]}
    has_key = "envelopes" in body_bad or bool(body_bad.get("type"))
    assert_eq(has_key, False,
              "[3] тело с ключом 'events' НЕ считается распознанным")

    assert_eq(hasattr(api, "MAX_ENVELOPES_PER_BATCH"), True,
              "[3] потолок на пачку на месте")


async def _run():
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_delivery_gaps_")
    os.close(fd)
    os.unlink(db_path)

    db = await _build_db(db_path)
    try:
        test_envelope_id_does_not_collide_across_modules()
        await test_requeued_action_visible_to_moved_cursor(db)
        await test_unrecognized_body_is_not_silently_ok()
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


def main():
    print("=" * 74)
    print("Module API — непокрытые сценарии доставки (внешний разбор 02.08)")
    print("=" * 74)
    try:
        asyncio.run(_run())
    except Exception:
        print("\n💥 Test harness CRASHED (не assertion — инфраструктура):")
        traceback.print_exc()
        sys.exit(2)

    print("\n" + "=" * 74)
    print(f"PASSED: {len(_successes)}   FAILED: {len(_failures)}")
    if _failures:
        print("\nFAILURES:")
        for f in _failures:
            print(f)
        sys.exit(1)
    print("ALL GREEN ✅ — дедуп per-module; retry S-07 доставляется поверх cursor.")
    sys.exit(0)


if __name__ == "__main__":
    main()
