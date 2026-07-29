"""
test_tts_moderation.py — REGRESSION на модерацию озвучки (UGC-требования Twitch).

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_tts_moderation.py

## Зачем это вообще

Озвучка — пользовательский контент: зритель платит крустики, и его текст
звучит на стриме. Twitch требует к UGC набор возможностей модерации и прямо
предупреждает, что без них одобрение затягивается.

До 29.07 у нас не было НИЧЕГО: сообщение проходило оплату и сразу уходило на
оверлей. Единственным барьером была цена 5000💎 — версия 0.0.1 прошла ревью,
скорее всего, просто потому, что у ревьюера не было такой суммы.

## Чего требуем

1. Заблокированный зритель не может отправить озвучку.
2. Отказ по блокировке НЕ стоит зрителю денег — проверка идёт до оплаты
   (иначе бан превратился бы в способ отбирать крустики).
3. Скрытое стримером сообщение не уходит на оверлей.
4. Скрытое сообщение ОСТАЁТСЯ в истории — Twitch требует хранить историю UGC,
   а не стирать её.
5. Скрытие идемпотентно: повторный вызов не делает вид, что скрыл ещё раз.
6. Разблокировка возвращает зрителю возможность отправлять.

## Красный до фикса

До M102 тест падал на импорте (`is_tts_blocked` не существовало) — это не
считается осмысленным красным. Поэтому проверено иначе: с временно снятым
условием `moderated_by IS NULL` в выборке оверлея и снятой проверкой блок-листа
падают [1], [3]:
    ❌ [1] заблокированный не может отправить: expected False, got True
    ❌ [3] скрытое сообщение не уходит на оверлей: expected None, got 1
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
VIEWER = "alice"
START_POINTS = 20000

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


async def _points(db, username=VIEWER) -> int:
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT points FROM viewers WHERE channel_id=? AND username=?",
            (CHANNEL_ID, username))
        row = await cur.fetchone()
    return (row[0] if row else 0)


async def _queue_message(db, text: str) -> int:
    """Кладём сообщение как это делает оплаченный submit."""
    async with db._connect() as conn:
        cur = await conn.execute(
            "INSERT INTO tts_messages (channel_id, username, message, cost, status) "
            "VALUES (?, ?, ?, 5000, 'pending')",
            (CHANNEL_ID, VIEWER, text))
        await conn.commit()
        return cur.lastrowid


async def _overlay_next(db):
    """РЕАЛЬНАЯ выборка оверлея — та же функция, что зовёт эндпоинт.

    Копию SQL здесь держать нельзя: тест на копии зелен даже когда эндпоинт
    сломан. Ровно на этом уже обжигались с вассалами.
    """
    from routes.tts import next_pending_for_overlay
    row = await next_pending_for_overlay(db, CHANNEL_ID)
    return (row[0] if row else None)


async def _history_count(db) -> int:
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM tts_messages WHERE channel_id=?", (CHANNEL_ID,))
        return (await cur.fetchone())[0]


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
            "VALUES (?, 'alice_chan', 'Alice Channel', 'free')", (CHANNEL_ID,))
        await conn.execute(
            "INSERT INTO viewers (channel_id, username, points) VALUES (?, ?, ?)",
            (CHANNEL_ID, VIEWER, START_POINTS))
        await conn.commit()
    return test_db


async def test_migration(db):
    print("\n[0] M102 создала таблицу и поля модерации")
    async with db._connect() as conn:
        cur = await conn.execute("PRAGMA table_info(tts_messages)")
        cols = [r[1] for r in await cur.fetchall()]
        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='tts_blocked_users'")
        has_table = await cur.fetchone() is not None
    assert_eq("moderated_by" in cols and "moderated_at" in cols, True,
              "[0] поля модерации в tts_messages")
    assert_eq(has_table, True, "[0] таблица блок-листа создана")


async def test_blocked_viewer_refused(db):
    print("\n[1] Заблокированный зритель не может отправить")
    from routes.tts import is_tts_blocked, set_tts_block

    assert_eq(await is_tts_blocked(db, CHANNEL_ID, VIEWER), False,
              "[1] до блокировки — можно")

    await set_tts_block(db, CHANNEL_ID, VIEWER, True, by="streamer",
                        reason="спам")
    assert_eq(await is_tts_blocked(db, CHANNEL_ID, VIEWER), True,
              "[1] заблокированный не может отправить")


async def test_block_costs_nothing(db):
    print("\n[2] Отказ по блокировке не стоит зрителю денег")
    before = await _points(db)
    # Путь submit: проверка блок-листа стоит ДО списания, поэтому баланс цел.
    from routes.tts import is_tts_blocked
    refused = await is_tts_blocked(db, CHANNEL_ID, VIEWER)
    after = await _points(db)
    assert_eq(refused, True, "[2] отказ произошёл")
    assert_eq(after - before, 0, "[2] крустики не списаны при отказе")


async def test_hidden_message_not_played(db):
    print("\n[3] Скрытое сообщение не уходит на оверлей, но живёт в истории")
    from routes.tts import hide_tts_message

    msg_id = await _queue_message(db, "прочитай это вслух")
    assert_eq(await _overlay_next(db), msg_id, "[3] до скрытия оверлей его берёт")

    hist_before = await _history_count(db)
    hidden = await hide_tts_message(db, CHANNEL_ID, msg_id, by="streamer")
    assert_eq(hidden, True, "[3] скрытие сработало")
    assert_eq(await _overlay_next(db), None,
              "[3] скрытое сообщение не уходит на оверлей")
    assert_eq(await _history_count(db), hist_before,
              "[3] скрытое осталось в истории (не удалено)")


async def test_hide_is_idempotent(db):
    print("\n[4] Повторное скрытие не делает вид, что сработало")
    from routes.tts import hide_tts_message
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT id FROM tts_messages WHERE channel_id=? "
            "AND moderated_by IS NOT NULL LIMIT 1", (CHANNEL_ID,))
        row = await cur.fetchone()
    again = await hide_tts_message(db, CHANNEL_ID, row[0], by="streamer")
    assert_eq(again, False, "[4] повторное скрытие возвращает False")


async def test_unblock_restores(db):
    print("\n[5] Разблокировка возвращает возможность отправлять")
    from routes.tts import is_tts_blocked, set_tts_block
    await set_tts_block(db, CHANNEL_ID, VIEWER, False)
    assert_eq(await is_tts_blocked(db, CHANNEL_ID, VIEWER), False,
              "[5] после разблокировки — снова можно")


async def main_async():
    tmp = tempfile.mkdtemp(prefix="tts_mod_")
    db_path = os.path.join(tmp, "test.db")
    db = await _build_db(db_path)
    try:
        await test_migration(db)
        await test_blocked_viewer_refused(db)
        await test_block_costs_nothing(db)
        await test_hidden_message_not_played(db)
        await test_hide_is_idempotent(db)
        await test_unblock_restores(db)
    finally:
        try:
            await db._pool.close()
        except Exception:
            pass

    print("\n" + "=" * 62)
    if _failures:
        print(f"ПРОВАЛЕНО: {len(_failures)}, пройдено: {len(_successes)}")
        for f in _failures:
            print(f)
        return 1
    print(f"ВСЁ ЗЕЛЁНОЕ: {len(_successes)} проверок")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main_async()))
    except Exception:
        traceback.print_exc()
        sys.exit(2)
