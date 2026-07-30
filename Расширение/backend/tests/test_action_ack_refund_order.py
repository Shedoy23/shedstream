"""
test_action_ack_refund_order.py — REGRESSION на T-02 (внешний триаж 2026-07-27,
подтверждён мной на боевой базе 2026-07-28).

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_action_ack_refund_order.py

## Что за дыра

Мод отвечает из `ExecuteAsync` РАНЬШЕ, чем реально выполняет действие. Поэтому
`action.failed` иногда приходит на бэкенд раньше, чем поллер пришлёт
`ACK success=true`. Тогда:

1. `_on_action_failed` возвращает крустики и пишет маркер `REFUNDED:…` в
   `module_actions.error_msg`, **статус строки не меняя**;
2. следом `Database.ack_action` делает
   `SET status=?, error_msg=? WHERE status IN ('queued','dispatched')` —
   условие выполняется, `error_msg` перезаписывается в NULL, статус → `acked`.

Маркер `REFUNDED:` — ЕДИНСТВЕННАЯ защита от повторного возврата
(`modules/bannerlord/_adapter.py`). Он стёрт → защита снята. Следующий
`action.failed` по тому же действию вернёт деньги ВТОРОЙ раз.

На проде 27.07 так вышло минимум у четырёх действий: `status=acked`,
`error_msg=NULL`, при этом в логе по двум видно `REFUND ok +50`.

## Чего требуем от правильного поведения

- `ACK(success) → failed` — ШТАТНЫЙ поток (мод подтверждает до работы, потом
  сообщает об отказе): возврат обязан пройти. Это регресс-сторож, не даёт
  «починить» дыру, сломав нормальный путь.
- `failed → ACK(success)` — деньги уже вернули: поздний ACK не должен ни
  стирать маркер, ни объявлять действие успешным.
- `failed → failed` — второго возврата нет.
- `failed → ACK → failed` — ГЛАВНОЕ: второго возврата нет. Именно эта
  последовательность сегодня приводит к двойной выплате.

## Тест видели красным (правило CLAUDE.md 2b)

До фикса, на текущем коде:
    ❌ [A] маркер возврата пережил ACK: expected True, got False
    ❌ [A] статус после отказа терминальный (не acked): expected 'failed', got 'acked'
    ❌ [B] failed → ACK → failed НЕ вернул деньги второй раз: expected 50, got 100
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
START_POINTS = 1_000
PRICE = 50

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


async def _points(db, username="alice"):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT points FROM viewers WHERE channel_id=? AND username=?",
            (CHANNEL_ID, username))
        row = await cur.fetchone()
    return (row[0] if row else 0)


async def _row(db, action_id):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT status, COALESCE(error_msg,'') FROM module_actions "
            "WHERE channel_id=? AND module_id='bannerlord' AND action_id=?",
            (CHANNEL_ID, action_id))
        return await cur.fetchone()


async def _new_action(db, action_id, price=PRICE):
    """Кладём оплаченное действие в очередь (как это делает касса)."""
    import json
    data = {"initiated_by": "alice", "target": "alice", "price": price}
    async with db._connect() as conn:
        await conn.execute(
            "INSERT INTO module_actions "
            "(channel_id, module_id, action_id, type, data, status) "
            "VALUES (?, 'bannerlord', ?, 'player.spawn', ?, 'queued')",
            (CHANNEL_ID, action_id, json.dumps(data, ensure_ascii=False)))
        await conn.commit()


async def _send_failed(action_id, reason="test_refuse"):
    # discover_modules() обязателен: реестр наполняется на старте приложения
    # (main.py), в тесте его надо поднять руками, иначе get_module вернёт None.
    from modules._loader import get_module, discover_modules
    from modules._base import ModuleEnvelope
    adapter = get_module("bannerlord") or discover_modules().get("bannerlord")
    if adapter is None:
        raise RuntimeError("модуль bannerlord не загрузился — проверь manifest.yaml")
    await adapter.handle_event(CHANNEL_ID, ModuleEnvelope(
        id=action_id, kind="event", type="action.failed", ts=0,
        data={"action_id": action_id, "reason": reason}))


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
            "INSERT INTO viewers (channel_id, username, points) VALUES (?, 'alice', ?)",
            (CHANNEL_ID, START_POINTS))
        await conn.commit()
    return test_db


async def test_normal_ack_then_failed(db):
    """ШТАТНЫЙ поток: мод подтвердил (до работы), потом сообщил об отказе."""
    print("\n[Ш] Штатный порядок: ACK(успех) → отказ. Возврат обязан пройти")
    aid = "order-ack-then-failed"
    await _new_action(db, aid)
    before = await _points(db)

    await db.ack_action(channel_id=CHANNEL_ID, module_id="bannerlord",
                        action_id=aid, success=True, error_msg=None)
    await _send_failed(aid)

    assert_eq(await _points(db) - before, PRICE,
              "[Ш] поздний отказ вернул деньги (штатный путь не сломан)")


async def test_failed_then_ack_keeps_marker(db):
    """Отказ пришёл ПЕРВЫМ. Поздний ACK не должен ни стирать маркер, ни врать о статусе."""
    print("\n[A] Обратный порядок: отказ → ACK(успех)")
    aid = "order-failed-then-ack"
    await _new_action(db, aid)
    before = await _points(db)

    await _send_failed(aid)
    assert_eq(await _points(db) - before, PRICE, "[A] отказ вернул деньги")
    status, err = await _row(db, aid)
    assert_eq(err.startswith("REFUNDED:"), True, "[A] маркер возврата записан")

    # Поздний ACK об успехе — действие УЖЕ провалено и оплачено обратно.
    await db.ack_action(channel_id=CHANNEL_ID, module_id="bannerlord",
                        action_id=aid, success=True, error_msg=None)

    status, err = await _row(db, aid)
    assert_eq(err.startswith("REFUNDED:"), True, "[A] маркер возврата ПЕРЕЖИЛ ACK")
    assert_eq(status, "failed", "[A] статус после отказа терминальный (не acked)")


async def test_no_double_refund(db):
    """Дубликаты и главная последовательность: failed → ACK → failed."""
    print("\n[B] Повторы: отказ → отказ, и отказ → ACK → отказ")

    aid = "order-failed-twice"
    await _new_action(db, aid)
    before = await _points(db)
    await _send_failed(aid)
    await _send_failed(aid)
    assert_eq(await _points(db) - before, PRICE,
              "[B] два отказа подряд вернули деньги ОДИН раз")

    aid2 = "order-failed-ack-failed"
    await _new_action(db, aid2)
    before2 = await _points(db)
    await _send_failed(aid2)
    await db.ack_action(channel_id=CHANNEL_ID, module_id="bannerlord",
                        action_id=aid2, success=True, error_msg=None)
    await _send_failed(aid2)          # ← сюда и приходит двойная выплата
    assert_eq(await _points(db) - before2, PRICE,
              "[B] failed → ACK → failed НЕ вернул деньги второй раз")


async def test_concurrent_failed_single_refund(db):
    """ОДНОВРЕМЕННЫЕ отказы: возврат ровно один раз (хвост 1 из DEFERRED §C0-bis).

    Зачем отдельно от [B]. Тест выше отправляет отказы ПОСЛЕДОВАТЕЛЬНО — второй
    начинается, когда первый уже дописал маркер `REFUNDED:`. Такой прогон
    доказывает только идемпотентность «по факту записи», но НЕ то, что защита
    держит настоящую гонку: два события приходят одновременно, оба читают строку
    ДО того, как кто-то успел поставить маркер.

    Защита в коде структурная: `BEGIN IMMEDIATE` берётся ДО `SELECT`, поэтому
    второй вызов ждёт write-lock и после разблокировки видит уже записанный
    маркер. Но это была ЗАЯВКА из чтения кода — теста с реальной конкуренцией не
    существовало. Проверять это важно именно здесь: двойная выплата на этом пути
    уже случалась на проде с четырьмя действиями (T-02).

    **ЧТО ИМЕННО ДЕРЖИТ `BEGIN IMMEDIATE` — выяснено экспериментом 30.07.**
    Первая версия этого теста смотрела только на сумму возврата и осталась
    ЗЕЛЁНОЙ, когда `IMMEDIATE` заменили на обычный `BEGIN`. Разбор показал:
      • деньги и в этом случае вернулись один раз — их держат маркер `REFUNDED:`
        и блокировка SQLite, а не выбор режима транзакции;
      • но один из обработчиков ПАДАЛ с `database is locked`, то есть событие
        терялось с ошибкой вместо аккуратного «already refunded, skip».
    Поэтому тест проверяет ДВА инварианта: сумму возврата И отсутствие ошибок
    в логе обработчика. Без второй проверки он не отличает наличие защиты от её
    отсутствия — то есть не доказывает ничего.
    """
    print("\n[C] Гонка: одновременные отказы возвращают деньги ОДИН раз")

    import logging

    class _ErrorCatcher(logging.Handler):
        """Собирает ERROR-записи обработчика: упавшее событие = потерянное."""

        def __init__(self):
            super().__init__(level=logging.ERROR)
            self.records: list = []

        def emit(self, record):
            self.records.append(record.getMessage())

    catcher = _ErrorCatcher()
    mod_logger = logging.getLogger("rimlink.modules.bannerlord")
    mod_logger.addHandler(catcher)

    # (a) Два одновременных отказа.
    aid = "order-failed-concurrent-2"
    await _new_action(db, aid)
    before = await _points(db)
    results = await asyncio.gather(_send_failed(aid), _send_failed(aid),
                                   return_exceptions=True)
    errors = [r for r in results if isinstance(r, Exception)]
    assert_eq(errors, [], "[C] ни один из двух одновременных отказов не упал")
    assert_eq(await _points(db) - before, PRICE,
              "[C] ДВА ОДНОВРЕМЕННЫХ отказа вернули деньги ровно один раз")
    status, err = await _row(db, aid)
    assert_eq(err.startswith("REFUNDED:"), True, "[C] маркер возврата записан")

    # (b) Пять одновременных — если защита держится только на «повезло с
    # порядком», на пяти это проявится охотнее, чем на двух.
    aid5 = "order-failed-concurrent-5"
    await _new_action(db, aid5)
    before5 = await _points(db)
    results5 = await asyncio.gather(*[_send_failed(aid5) for _ in range(5)],
                                    return_exceptions=True)
    errors5 = [r for r in results5 if isinstance(r, Exception)]
    assert_eq(errors5, [], "[C] ни один из пяти одновременных отказов не упал")
    got = await _points(db) - before5
    assert_eq(got, PRICE,
              f"[C] ПЯТЬ одновременных отказов вернули ровно {PRICE}, а не кратное")

    # (c) Главная проверка чувствительности: обработчик не должен НИ РАЗУ
    # свалиться. Именно это ломается, если `BEGIN IMMEDIATE` ослабить до `BEGIN`
    # — событие теряется с `database is locked`, а сумма при этом остаётся
    # правильной, поэтому проверка суммы такую регрессию НЕ ловит.
    mod_logger.removeHandler(catcher)
    if catcher.records:
        print("      записи ERROR из обработчика:")
        for m in catcher.records[:5]:
            print(f"        · {m[:160]}")
    assert_eq(catcher.records, [],
              "[C] обработчик не залогировал ни одной ошибки (нет 'database is locked')")


class _AckRequest:
    """Минимальный Request для маршрутов /v1/module/<id>/ack и /events."""

    def __init__(self, payload, token="test-token"):
        self._payload = payload
        self.headers = {"Authorization": f"Bearer {token}"}
        self.client = None

    async def json(self):
        return self._payload


async def _call_ack_route(action_id: str, success: bool, reason: str = "forged_retry"):
    """Дёргаем НАСТОЯЩИЙ маршрут ACK, а не адаптер напрямую.

    Именно этого не хватало: тесты ниже ходили в `handle_event`, поэтому
    повторный запрос К МАРШРУТУ никем не проверялся.
    """
    import routes.module_api as api
    api._verify_module_request = lambda request, module_id: CHANNEL_ID
    body = {"action_id": action_id, "success": success}
    if not success:
        body["error"] = reason
    return await api.module_ack("bannerlord", _AckRequest(body))


async def test_repeat_ack_does_not_refund_done_action(db):
    """[5] ВНЕШНИЙ АУДИТ 31.07 (КРИТИЧНО): повторный ACK делал выполненное
    действие бесплатным.

    Маршрут `/ack` не смотрел на результат `ack_action`. Тот возвращает False,
    когда строка НЕ перешла из queued/dispatched — то есть действие уже
    завершено. А синтетический `action.failed` запускался всё равно, и зритель
    получал полную цену обратно, СОХРАНИВ эффект в игре.

    Воспроизведение аудитора: acked=False, points +50, строка → failed
    с маркером возврата.
    """
    print("\n[5] Повторный ACK по выполненному действию НЕ возвращает деньги")
    aid = "ack-replay-1"
    await _new_action(db, aid)
    before = await _points(db)

    first = await _call_ack_route(aid, success=True)
    assert_eq(first.get("acked"), True, "[5] первый ACK принят")

    second = await _call_ack_route(aid, success=False)
    assert_eq(second.get("acked"), False, "[5] повторный ACK не принят")

    after = await _points(db)
    row = await _row(db, aid)
    assert_eq(after - before, 0, "[5] крустики НЕ возвращены (эффект остаётся)")
    assert_eq(row[0], "acked", "[5] строка осталась выполненной, не 'failed'")
    assert_eq((row[1] or "").startswith("REFUNDED:"), False,
              "[5] маркер возврата не проставлен")


async def test_honest_failure_ack_still_refunds(db):
    """[6] Обратная сторона: честный отказ через тот же маршрут ОБЯЗАН вернуть.

    Без этой проверки фикс [5] мог бы просто выключить возвраты целиком.
    """
    print("\n[6] Честный отказ через маршрут ACK по-прежнему возвращает деньги")
    aid = "ack-honest-fail-1"
    await _new_action(db, aid)
    before = await _points(db)

    res = await _call_ack_route(aid, success=False, reason="mod_refused")
    assert_eq(res.get("acked"), True, "[6] отказ принят маршрутом")

    after = await _points(db)
    row = await _row(db, aid)
    assert_eq(after - before, PRICE, f"[6] возвращена полная цена ({PRICE})")
    assert_eq(row[0], "failed", "[6] строка помечена failed")
    assert_eq((row[1] or "").startswith("REFUNDED:"), True,
              "[6] маркер возврата проставлен")


async def test_late_async_failure_event_still_refunds(db):
    """[7] Поздний отказ мода приходит СОБЫТИЕМ, а не в /ack — он должен жить.

    Хендлеры мода часто ACK'ают true сразу, а работу делают в главном потоке и
    падают позже; тогда `ActionFeedback.PostFailed` шлёт `action.failed`.
    Фикс [5] обязан этот путь не задеть — иначе зритель платит за не
    случившееся.
    """
    print("\n[7] Поздний отказ событием возвращает деньги и после ACK-успеха")
    aid = "late-async-fail-1"
    await _new_action(db, aid)
    before = await _points(db)

    await _call_ack_route(aid, success=True)
    await _send_failed(aid, reason="in_mission")

    after = await _points(db)
    assert_eq(after - before, PRICE,
              f"[7] поздний отказ вернул цену ({PRICE}) — путь не сломан")


async def test_failed_envelope_can_be_retried(db):
    """[8] ВНЕШНИЙ АУДИТ 31.07 (находка 4): упавший конверт не должен
    объявляться дубликатом.

    `_is_duplicate_envelope` помечал id увиденным В МОМЕНТ ПРОВЕРКИ, до вызова
    обработчика. Падение обработчика — и повтор с тем же id получал
    `duplicate: true, success: true`, то есть НЕ исполнялся. А `action.failed`
    это заявка на ВОЗВРАТ денег, и мод шлёт её одним запросом без повторов:
    одного сбоя хватало, чтобы возврат исчез, а списание осталось.

    ЧЕСТНО О ГРАНИЦАХ: тест проверяет книгу учёта конвертов и то, что после
    «забывания» повтор реально доводит возврат до конца. Полный HTTP-маршрут
    `/events` он не поднимает (там своя проверка токена) — маршрут вызывает
    ровно эти же две функции, но это стык, который тестом не покрыт.
    """
    print("\n[8] Упавший конверт можно повторить, а не считать дубликатом")
    import routes.module_api as api

    aid = "envelope-retry-1"
    await _new_action(db, aid)
    before = await _points(db)

    # Так делает маршрут: сначала проверка-и-пометка, потом обработчик.
    assert_eq(api._is_duplicate_envelope(CHANNEL_ID, aid), False,
              "[8] первый конверт не дубликат")

    # Обработчик упал → маршрут обязан ЗАБЫТЬ конверт.
    api._forget_envelope(CHANNEL_ID, aid)

    assert_eq(api._is_duplicate_envelope(CHANNEL_ID, aid), False,
              "[8] повтор упавшего конверта НЕ считается дубликатом")

    # Повтор доводит возврат до конца.
    await _send_failed(aid, reason="retry_after_failure")
    assert_eq(await _points(db) - before, PRICE,
              f"[8] повтор довёл возврат до конца ({PRICE})")

    # А успешно обработанный конверт по-прежнему дедуплицируется.
    api._is_duplicate_envelope(CHANNEL_ID, "envelope-ok-1")
    assert_eq(api._is_duplicate_envelope(CHANNEL_ID, "envelope-ok-1"), True,
              "[8] обычный дедуп не сломан")


async def _run():
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_ack_order_")
    os.close(fd)
    os.unlink(db_path)

    db = await _build_db(db_path)
    try:
        await test_normal_ack_then_failed(db)
        await test_failed_then_ack_keeps_marker(db)
        await test_no_double_refund(db)
        await test_concurrent_failed_single_refund(db)
        await test_repeat_ack_does_not_refund_done_action(db)
        await test_honest_failure_ack_still_refunds(db)
        await test_late_async_failure_event_still_refunds(db)
        await test_failed_envelope_can_be_retried(db)
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
    print("REGRESSION T-02: порядок ACK и возврата (защита от двойной выплаты)")
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
    print("ALL GREEN ✅ — порядок ACK/возврата безопасен.")
    sys.exit(0)


if __name__ == "__main__":
    main()
