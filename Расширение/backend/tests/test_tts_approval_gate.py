"""
test_tts_approval_gate.py — гейт предварительного одобрения озвучки (M107).

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_tts_approval_gate.py

## Зачем гейт

Twitch Extensions Guidelines §7.2 (получено 2026-08-01):

    «Extensions must provide broadcasters with the ability to review, and
     reject or approve any image or other audio-visual user content that has
     been submitted through an Extension on their channel.»

Озвучка на оверлее — это audio-visual user content. Реактивной модерации
(M102: скрыть постфактум, заблокировать автора) для §7.2 НЕ хватает: оверлей
опрашивает очередь раз в 3 секунды, и «отклонить» сообщение, которое уже
прозвучало в эфире, физически невозможно.

## Что проверяем

Тест бьёт в `next_pending_for_overlay` — ТУ ЖЕ функцию, которую реально
вызывает эндпоинт оверлея, а не свою копию запроса.

1. Гейт включён по умолчанию, даже когда строки настроек нет вообще
   (канал без записи не должен оказаться каналом без модерации).
2. При включённом гейте неодобренное сообщение оверлею НЕ отдаётся.
3. Одобренное — отдаётся.
4. Скрытое не отдаётся даже после одобрения, и одобрить скрытое нельзя.
5. Переключатель возвращает прежнее поведение: гейт выключен → играет сразу.
   Это и есть «на свой страх и риск» — проверяем, что риск реален, а не
   декоративен.
6. Повторное одобрение не проходит (кнопка не двоит состояние).
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
OTHER_CHANNEL = 12345678

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


async def _add_message(db, channel_id: int, username: str, text: str) -> int:
    async with db._connect() as conn:
        cur = await conn.execute(
            "INSERT INTO tts_messages (channel_id, username, message, cost, status) "
            "VALUES (?, ?, ?, 5000, 'pending')",
            (channel_id, username, text))
        await conn.commit()
        return cur.lastrowid


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


async def test_gate_on_by_default(db):
    """Гейт включён из коробки — в том числе у канала без строки настроек."""
    print("\n[1] Гейт включён по умолчанию")
    import routes.tts as tts

    assert_eq(await tts.tts_requires_approval(db, CHANNEL_ID), True,
              "у канала с записью гейт включён")
    # Канала OTHER_CHANNEL нет в channel_tts_settings вовсе.
    assert_eq(await tts.tts_requires_approval(db, OTHER_CHANNEL), True,
              "у канала БЕЗ записи гейт тоже включён (не открываем дверь молча)")


async def test_unapproved_not_played(db):
    """Неодобренное сообщение оверлей не получает."""
    print("\n[2] §7.2: без одобрения в эфир не идёт")
    import routes.tts as tts

    msg_id = await _add_message(db, CHANNEL_ID, "bob", "привет стрим")
    row = await tts.next_pending_for_overlay(db, CHANNEL_ID)
    assert_eq(row, None, "неодобренное сообщение оверлею НЕ отдано")

    approved = await tts.approve_tts_message(db, CHANNEL_ID, msg_id)
    assert_eq(approved, True, "одобрение прошло")

    row = await tts.next_pending_for_overlay(db, CHANNEL_ID)
    assert_eq(row[0] if row else None, msg_id, "после одобрения оверлей его берёт")

    assert_eq(await tts.approve_tts_message(db, CHANNEL_ID, msg_id), False,
              "повторное одобрение не проходит")


async def test_hidden_stays_silent(db):
    """Скрытое не звучит и одобрить его нельзя."""
    print("\n[3] Скрытое сообщение не воскрешается одобрением")
    import routes.tts as tts

    msg_id = await _add_message(db, CHANNEL_ID, "carol", "плохое сообщение")
    await tts.hide_tts_message(db, CHANNEL_ID, msg_id, by=str(CHANNEL_ID))

    assert_eq(await tts.approve_tts_message(db, CHANNEL_ID, msg_id), False,
              "скрытое сообщение одобрить нельзя")

    # В очереди осталось только одобренное из теста [2] — но оно уже отдано;
    # проверяем, что скрытое не всплывает как следующее.
    async with db._connect() as conn:
        await conn.execute(
            "UPDATE tts_messages SET status='played' WHERE channel_id=? AND approved_at IS NOT NULL",
            (CHANNEL_ID,))
        await conn.commit()
    row = await tts.next_pending_for_overlay(db, CHANNEL_ID)
    assert_eq(row, None, "скрытое не становится следующим в очереди")


async def test_toggle_restores_instant_play(db):
    """Переключатель реально выключает гейт — риск не декоративный."""
    print("\n[4] Переключатель «на свой страх и риск» работает")
    import routes.tts as tts

    msg_id = await _add_message(db, CHANNEL_ID, "dave", "без модерации")
    assert_eq(await tts.next_pending_for_overlay(db, CHANNEL_ID), None,
              "при включённом гейте не звучит")

    await tts.set_tts_require_approval(db, CHANNEL_ID, False)
    assert_eq(await tts.tts_requires_approval(db, CHANNEL_ID), False,
              "гейт выключен")

    row = await tts.next_pending_for_overlay(db, CHANNEL_ID)
    assert_eq(row[0] if row else None, msg_id,
              "с выключенным гейтом сообщение идёт в эфир без одобрения")

    # Скрытие обязано работать и при выключенном гейте — это §7.4, отдельное
    # требование, которое переключатель не отменяет.
    await tts.hide_tts_message(db, CHANNEL_ID, msg_id, by=str(CHANNEL_ID))
    assert_eq(await tts.next_pending_for_overlay(db, CHANNEL_ID), None,
              "скрытие работает и с выключенным гейтом (§7.4)")

    await tts.set_tts_require_approval(db, CHANNEL_ID, True)
    assert_eq(await tts.tts_requires_approval(db, CHANNEL_ID), True,
              "гейт включается обратно")


async def _run():
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_tts_gate_")
    os.close(fd)
    os.unlink(db_path)

    db = await _build_db(db_path)
    try:
        await test_gate_on_by_default(db)
        await test_unapproved_not_played(db)
        await test_hidden_stays_silent(db)
        await test_toggle_restores_instant_play(db)
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
    print("=" * 70)
    print("M107: гейт одобрения озвучки (Twitch Guidelines §7.2)")
    print("=" * 70)
    try:
        asyncio.run(_run())
    except Exception:
        print("\n💥 Test harness CRASHED (не assertion — инфраструктура):")
        traceback.print_exc()
        sys.exit(2)

    print("\n" + "=" * 70)
    print(f"PASSED: {len(_successes)}   FAILED: {len(_failures)}")
    if _failures:
        print("\nFAILURES:")
        for f in _failures:
            print(f)
        sys.exit(1)
    print("ALL GREEN ✅ — без одобрения озвучка в эфир не идёт.")
    sys.exit(0)


if __name__ == "__main__":
    main()
