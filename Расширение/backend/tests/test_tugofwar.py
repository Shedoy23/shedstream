"""
test_tugofwar.py — «Перетягивание каната»: награда не за исход, случайности нет.

Standalone (без pytest). Запуск из backend/:
    python tests/test_tugofwar.py

ЗАЧЕМ. Канат заменяет кубики (решение владельца 2026-09-01). Механику до
написания кода прогнали через комплаенс-ревью
(`docs/specs/SPEC_TUG_OF_WAR_COMPLIANCE_JIM_2026-08-26.md`, вердикт
PASS-WITH-CHANGES). Ревью назвало четыре блокера, и каждый из них здесь —
проверка, а не обещание в докстринге:

1. **Крустики не зависят от исхода.** Иначе получается цепочка «выбрал сторону →
   исход зависит не от тебя → получил валюту», а она читается как ставка —
   особенно после того, как это же расширение уже щёлкнули по правилу 3.5.
2. **Случайности нет нигде.** Ни в распределении по командам, ни в разрешении
   ничьей. Проверяем грепом по модулю: обещаниям тут веры нет.
3. **Сторона фиксируется, приём закрывается.** Перебежать в выигрывающую
   команду нельзя, войти после закрытия приёма нельзя.
4. **Нормировка заморожена.** Размер команды фиксируется на закрытии приёма;
   поздний участник не меняет задним числом ценность чужих тапов.

Плюс две вещи, которые ревью не называло, но которые ломаются тихо:

5. Кредит выдаётся ОДИН раз, сколько бы раз ни прочитали статус.
6. Раунд одного канала не виден другому.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
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


def assert_eq(actual, expected, label: str):
    if actual == expected:
        print(f"  OK  {label}")
    else:
        msg = f"  FAIL {label}: expected {expected!r}, got {actual!r}"
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
        for cid, login in ((CHANNEL_ID, "alice_chan"), (OTHER_CHANNEL, "bob_chan")):
            await conn.execute(
                "INSERT OR IGNORE INTO channels (channel_id, login, display_name, tier) "
                "VALUES (?, ?, ?, 'free')", (cid, login, login))
            for who in ("alice", "bob", "carol"):
                await conn.execute(
                    "INSERT INTO viewers (channel_id, username, points) VALUES (?, ?, 0)",
                    (cid, who))
        await conn.commit()
    return test_db


async def _points(db, channel_id, username):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT points FROM viewers WHERE channel_id=? AND username=?",
            (channel_id, username))
        row = await cur.fetchone()
    return row[0] if row else None


async def _close_join(db, channel_id):
    """Сдвинуть окно приёма в прошлое — фаза перейдёт при первом же чтении."""
    async with db._connect() as conn:
        await conn.execute(
            "UPDATE tug_rounds SET join_until=? WHERE channel_id=? AND status='join'",
            (time.time() - 1, channel_id))
        await conn.commit()


async def _end_pull(db, channel_id):
    async with db._connect() as conn:
        await conn.execute(
            "UPDATE tug_rounds SET pull_until=? WHERE channel_id=? AND status='pull'",
            (time.time() - 1, channel_id))
        await conn.commit()


async def _reset_cooldown(db, channel_id):
    async with db._connect() as conn:
        await conn.execute(
            "UPDATE tug_participants SET last_pull_at=0 WHERE channel_id=?",
            (channel_id,))
        await conn.commit()


async def test_reward_is_not_outcome_contingent(db, tug):
    print("\n[1] Крустики за участие, а не за победу")
    await tug.start_round(CHANNEL_ID, "Синие", "Красные")
    await tug.join_side("alice", CHANNEL_ID, "a")
    await tug.join_side("bob", CHANNEL_ID, "b")
    await _close_join(db, CHANNEL_ID)

    # alice тянет много, bob — ровно минимум. Победа достанется alice.
    for _ in range(3):
        await tug.pull_rope("alice", CHANNEL_ID, 10)
        await _reset_cooldown(db, CHANNEL_ID)
    await tug.pull_rope("bob", CHANNEL_ID, tug.QUALIFY_TAPS)
    await _reset_cooldown(db, CHANNEL_ID)

    await _end_pull(db, CHANNEL_ID)
    res = await tug.status_for("alice", CHANNEL_ID)

    assert_eq(res["round"]["result"], "a", "победила сторона, которая тянула сильнее")
    assert_eq(await _points(db, CHANNEL_ID, "alice"), tug.PARTICIPATION_CREDIT,
              "победитель получил фиксированный кредит за участие")
    assert_eq(await _points(db, CHANNEL_ID, "bob"), tug.PARTICIPATION_CREDIT,
              "ПРОИГРАВШИЙ получил РОВНО СТОЛЬКО ЖЕ")
    assert_eq(res["rules"]["outcome_reward"], 0,
              "в правилах прямо сказано: за исход крустики не начисляются")


async def test_below_floor_gets_nothing(db, tug):
    print("\n[2] Открыл панель и ушёл — кредита нет")
    await tug.start_round(CHANNEL_ID, "Синие", "Красные")
    await tug.join_side("carol", CHANNEL_ID, "a")
    await _close_join(db, CHANNEL_ID)
    await tug.pull_rope("carol", CHANNEL_ID, tug.QUALIFY_TAPS - 1)
    await _end_pull(db, CHANNEL_ID)
    await tug.status_for("carol", CHANNEL_ID)
    assert_eq(await _points(db, CHANNEL_ID, "carol"), 0,
              "ниже порога участия — ноль")


async def test_no_double_credit(db, tug):
    print("\n[3] Кредит выдаётся один раз, сколько статус ни читай")
    before = await _points(db, CHANNEL_ID, "alice")
    for _ in range(3):
        await tug.status_for("alice", CHANNEL_ID)
    assert_eq(await _points(db, CHANNEL_ID, "alice"), before,
              "повторные чтения статуса не начисляют ещё раз")


async def test_side_locked_and_join_closes(db, tug):
    print("\n[4] Сторону не поменять, после закрытия приёма не войти")
    await tug.start_round(CHANNEL_ID, "Синие", "Красные")
    await tug.join_side("alice", CHANNEL_ID, "a")
    again = await tug.join_side("alice", CHANNEL_ID, "b")
    assert_eq(again.get("success"), False, "перебежать в другую команду нельзя")
    assert_eq(again.get("side"), "a", "сторона осталась прежней")

    await _close_join(db, CHANNEL_ID)
    late = await tug.join_side("bob", CHANNEL_ID, "b")
    assert_eq(late.get("success"), False, "после закрытия приёма войти нельзя")


async def test_team_size_frozen(db, tug):
    print("\n[5] Размер команды заморожен на закрытии приёма")
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT team_a_size, team_b_size FROM tug_rounds "
            "WHERE channel_id=? ORDER BY id DESC LIMIT 1", (CHANNEL_ID,))
        team_a, team_b = await cur.fetchone()
    assert_eq(team_a, 1, "в команде A зафиксирован один участник")
    assert_eq(team_b, 0, "опоздавший в команду B не попал и делитель не изменил")
    await _end_pull(db, CHANNEL_ID)
    await tug.status_for("alice", CHANNEL_ID)


async def test_decay_and_determinism(db, tug):
    print("\n[6] Затухание есть, и оно детерминировано")
    ten = tug._batch_value(0, 10)
    assert_eq(ten < tug.TAP_BASE * 10, True,
              "десять тапов стоят дешевле десяти базовых — затухание работает")
    assert_eq(tug._batch_value(0, 10), ten, "тот же расчёт даёт тот же результат")
    assert_eq(tug._tap_value(10_000), tug.TAP_MIN,
              "цена тапа не падает ниже пола")
    assert_eq(tug._rope_pos(1000, 1000, 5, 5), 0,
              "равный вклад равных команд — канат посередине")
    assert_eq(tug._rope_pos(1000, 1000, 1, 10) > 0, True,
              "нормировка защищает малую команду")


async def test_draw_stays_draw(db, tug):
    print("\n[7] Ничья остаётся ничьёй — никакой монетки")
    await tug.start_round(OTHER_CHANNEL, "Синие", "Красные")
    await tug.join_side("alice", OTHER_CHANNEL, "a")
    await tug.join_side("bob", OTHER_CHANNEL, "b")
    await _close_join(db, OTHER_CHANNEL)
    await tug.pull_rope("alice", OTHER_CHANNEL, 6)
    await tug.pull_rope("bob", OTHER_CHANNEL, 6)
    await _end_pull(db, OTHER_CHANNEL)
    res = await tug.status_for("alice", OTHER_CHANNEL)
    assert_eq(res["round"]["result"], "draw", "равный вклад — ничья, а не победитель")
    assert_eq(await _points(db, OTHER_CHANNEL, "alice"), tug.PARTICIPATION_CREDIT,
              "при ничьей кредит всё равно выдан")
    assert_eq(await _points(db, OTHER_CHANNEL, "bob"), tug.PARTICIPATION_CREDIT,
              "обоим одинаково")


async def test_channel_isolation(db, tug):
    print("\n[8] Раунды каналов не видят друг друга")
    await tug.start_round(CHANNEL_ID, "Наши", "Ваши")
    mine = await tug.status_for("alice", CHANNEL_ID)
    other = await tug.status_for("alice", OTHER_CHANNEL)
    assert_eq(mine["round"]["side_a"], "Наши", "свой канал видит свой раунд")
    assert_eq(other.get("active"), False,
              "на соседнем канале активного раунда нет")


def test_no_randomness_in_module(tug):
    print("\n[9] В модуле нет ни одного обращения к случайности")
    src = Path(tug.__file__).read_text(encoding="utf-8")
    code = " ".join(line.split("#", 1)[0] for line in src.splitlines())
    # Ищем ИМПОРТ и ВЫЗОВ, а не слово: в докстринге модуля слово стоит
    # намеренно — там объясняется, почему случайности здесь нет.
    assert_eq("import random" not in code, True,
              "модуль каната не импортирует random")
    for call in ("random.", "randint(", "choice(", "shuffle(", "sample("):
        assert_eq(call not in code, True, f"нет вызова {call}")


async def _run():
    fd, db_path = tempfile.mkstemp(suffix=".db", prefix="test_tug_")
    os.close(fd)
    db = await _build_db(db_path)
    from routes import tugofwar as tug
    try:
        await test_reward_is_not_outcome_contingent(db, tug)
        await test_below_floor_gets_nothing(db, tug)
        await test_no_double_credit(db, tug)
        await test_side_locked_and_join_closes(db, tug)
        await test_team_size_frozen(db, tug)
        await test_decay_and_determinism(db, tug)
        await test_draw_stays_draw(db, tug)
        await test_channel_isolation(db, tug)
        test_no_randomness_in_module(tug)
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

    print("\n" + "=" * 70)
    if _failures:
        print(f"ПРОВАЛ: {len(_failures)}")
        for f in _failures:
            print(f)
        return 1
    print("ВСЁ ЗЕЛЁНОЕ — награда за участие, случайности нет, нормировка заморожена")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
