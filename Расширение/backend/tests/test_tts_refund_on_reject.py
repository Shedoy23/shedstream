"""
test_tts_refund_on_reject.py — отклонённая озвучка возвращает деньги и объясняет.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_tts_refund_on_reject.py

## Зачем

Озвучка — самое дорогое непрофильное действие панели: 5000💎. Оплата и эффект
разнесены во времени, потому что с 01.08 действует гейт предварительного
одобрения (M107), включённый по умолчанию даже у канала, где настройку никто не
трогал. Значит у платного действия появился исход «стример отклонил» — и до
07.09 этот исход не делал НИЧЕГО: `hide_tts_message` только помечал строку,
крустики оставались списанными, уведомления зритель не получал, статус заявки в
панели не показывается. Деньги списаны, эффекта нет, возврата нет.

На одном канале это незаметно: очередь модерации смотрит сам владелец. Публичный
релиз превращает это в правило — каждый новый стример, не открывший дашборд,
молча забирает у зрителей по 5000💎 за клик.

Класс ошибки известный и записан в `CLAUDE.md`: «платное + асинхронное действие»
обязано назвать исход на каждом выходе, а тост обязан говорить, что это заявка,
а не свершившийся факт.

## Чего требуем

1. Отклонение (`hide`) неозвученного сообщения возвращает РОВНО списанную сумму
   — ту, что записана в строке, а не текущую цену из конфига.
2. Возврат сопровождается уведомлением зрителю (`viewer_notices`), иначе деньги
   вернулись молча и зритель всё равно не знает, что произошло.
3. Возврат идемпотентен: второе отклонение той же строки не платит второй раз.
4. Отклонение УЖЕ ОЗВУЧЕННОГО сообщения денег не возвращает — услуга оказана.
5. Одобренное и озвученное сообщение остаётся платным (регрессия на п.1).
6. Заявка, по которой стример не решил вовсе, возвращает деньги по сроку
   (TTS_PENDING_TTL_S) — и после возврата прозвучать уже не может.
7. Повторный прогон подметалки не платит второй раз.

## Красный до фикса

С кодом `hide_tts_message` по состоянию на a380ad7 падают [1], [2] и [3]:
    ❌ [1] отклонение вернуло ровно списанное: expected 5000, got 0
    ❌ [2] зритель получил уведомление о возврате: expected True, got False
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
CHARGED = 5000

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


async def _queue_paid_message(db, text: str, cost: int = CHARGED,
                              status: str = "pending") -> int:
    """Кладём сообщение ТАК ЖЕ, как оплаченный submit: списание + строка.

    Списание здесь настоящее — иначе проверка «вернули ровно списанное»
    измеряла бы возврат в отрыве от кассы и прошла бы даже при двойной оплате.
    """
    async with db._connect() as conn:
        await conn.execute(
            "UPDATE viewers SET points = points - ? "
            "WHERE channel_id=? AND username=?",
            (cost, CHANNEL_ID, VIEWER))
        cur = await conn.execute(
            "INSERT INTO tts_messages (channel_id, username, message, cost, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (CHANNEL_ID, VIEWER, text, cost, status))
        await conn.commit()
        return cur.lastrowid


async def _notices_about_refund(db) -> int:
    async with db._connect() as conn:
        try:
            cur = await conn.execute(
                "SELECT COUNT(*) FROM viewer_notices "
                "WHERE channel_id=? AND username=? AND amount=?",
                (CHANNEL_ID, VIEWER, CHARGED))
            return (await cur.fetchone())[0]
        except Exception:
            return 0


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


async def test_reject_refunds_exactly(db):
    print("\n[1] Отклонение неозвученного возвращает ровно списанное")
    from routes.tts import hide_tts_message

    before = await _points(db)
    msg_id = await _queue_paid_message(db, "прочитай это вслух")
    after_charge = await _points(db)
    assert_eq(before - after_charge, CHARGED, "[1] списание состоялось")

    hidden = await hide_tts_message(db, CHANNEL_ID, msg_id, by="streamer")
    after_reject = await _points(db)
    assert_eq(hidden, True, "[1] отклонение сработало")
    assert_eq(after_reject - after_charge, CHARGED,
              "[1] отклонение вернуло ровно списанное")
    assert_eq(after_reject, before, "[1] баланс вернулся к исходному")


async def test_refund_is_explained(db):
    print("\n[2] Возврат объяснён зрителю, а не сделан молча")
    from routes.tts import hide_tts_message

    msg_id = await _queue_paid_message(db, "второе сообщение")
    await hide_tts_message(db, CHANNEL_ID, msg_id, by="streamer")
    assert_eq(await _notices_about_refund(db) > 0, True,
              "[2] зритель получил уведомление о возврате")


async def test_refund_not_paid_twice(db):
    print("\n[3] Повторное отклонение не платит второй раз")
    from routes.tts import hide_tts_message

    msg_id = await _queue_paid_message(db, "третье сообщение")
    await hide_tts_message(db, CHANNEL_ID, msg_id, by="streamer")
    after_first = await _points(db)

    again = await hide_tts_message(db, CHANNEL_ID, msg_id, by="streamer")
    after_second = await _points(db)
    assert_eq(again, False, "[3] повторное отклонение возвращает False")
    assert_eq(after_second - after_first, 0, "[3] второй возврат не начислен")


async def test_played_message_is_not_refunded(db):
    print("\n[4] Уже озвученное сообщение денег не возвращает")
    from routes.tts import hide_tts_message

    msg_id = await _queue_paid_message(db, "это уже прозвучало", status="played")
    after_charge = await _points(db)
    await hide_tts_message(db, CHANNEL_ID, msg_id, by="streamer")
    after_hide = await _points(db)
    assert_eq(after_hide - after_charge, 0,
              "[4] за оказанную услугу возврата нет")


async def _queue_aged_message(db, text: str, age_s: int, cost: int = CHARGED) -> int:
    """Заявка, поданная age_s секунд назад: списание + строка с прошлым created_at."""
    async with db._connect() as conn:
        await conn.execute(
            "UPDATE viewers SET points = points - ? "
            "WHERE channel_id=? AND username=?",
            (cost, CHANNEL_ID, VIEWER))
        cur = await conn.execute(
            "INSERT INTO tts_messages (channel_id, username, message, cost, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', datetime('now', ?))",
            (CHANNEL_ID, VIEWER, text, cost, f"-{age_s} seconds"))
        await conn.commit()
        return cur.lastrowid


async def test_stale_request_refunds_itself(db):
    print("\n[5] Заявка, по которой стример не решил, возвращает деньги по сроку")
    from config import TTS_PENDING_TTL_S
    from routes.tts import expire_stale_tts_requests

    fresh_id = await _queue_aged_message(db, "свежая заявка", age_s=60)
    stale_id = await _queue_aged_message(db, "забытая заявка",
                                         age_s=TTS_PENDING_TTL_S + 120)
    after_charge = await _points(db)
    # Считаем ПРИРОСТ уведомлений, а не «есть хоть одно»: к этому месту их уже
    # наделали проверки [1]-[3], и «> 0» было бы зелёным даже при немой
    # подметалке — тест, зелёный по неверной причине, хуже отсутствующего.
    notices_before = await _notices_about_refund(db)

    closed, refunded = await expire_stale_tts_requests(db)
    after_sweep = await _points(db)

    assert_eq(closed, 1, "[5] закрыта ровно одна — просроченная")
    assert_eq(refunded, CHARGED, "[5] вернули ровно списанное")
    assert_eq(after_sweep - after_charge, CHARGED, "[5] баланс зрителя вырос на возврат")
    assert_eq(await _notices_about_refund(db) - notices_before, 1,
              "[5] зритель извещён именно об этом возврате")

    # Свежая заявка не тронута: она ещё ждёт решения стримера.
    from routes.tts import approve_tts_message
    assert_eq(await approve_tts_message(db, CHANNEL_ID, fresh_id), True,
              "[5] свежую заявку всё ещё можно одобрить")
    # Просроченную одобрить уже нельзя — иначе зритель получил бы и деньги, и озвучку.
    assert_eq(await approve_tts_message(db, CHANNEL_ID, stale_id), False,
              "[5] возвращённую заявку одобрить нельзя")


async def test_sweep_does_not_pay_twice(db):
    print("\n[6] Повторный прогон подметалки не платит второй раз")
    from config import TTS_PENDING_TTL_S
    from routes.tts import expire_stale_tts_requests

    await _queue_aged_message(db, "ещё одна забытая", age_s=TTS_PENDING_TTL_S + 300)
    await expire_stale_tts_requests(db)
    after_first = await _points(db)

    closed, refunded = await expire_stale_tts_requests(db)
    after_second = await _points(db)
    assert_eq((closed, refunded), (0, 0), "[6] второй прогон ничего не нашёл")
    assert_eq(after_second - after_first, 0, "[6] второй возврат не начислен")


async def main_async():
    tmp = tempfile.mkdtemp(prefix="tts_refund_")
    db_path = os.path.join(tmp, "test.db")
    db = await _build_db(db_path)
    try:
        await test_reject_refunds_exactly(db)
        await test_refund_is_explained(db)
        await test_refund_not_paid_twice(db)
        await test_played_message_is_not_refunded(db)
        await test_stale_request_refunds_itself(db)
        await test_sweep_does_not_pay_twice(db)
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
