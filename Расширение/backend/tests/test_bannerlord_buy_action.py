"""
test_bannerlord_buy_action.py — CHARACTERIZATION test для "кассы" Bannerlord.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_bannerlord_buy_action.py

Цель: ЗАФИКСИРОВАТЬ ТЕКУЩЕЕ поведение
    routes/bannerlord.py → _bannerlord_buy_action_locked(...)
перед предстоящим рефакторингом. Это safety-net: тест должен быть ЗЕЛЁНЫМ
против текущего кода. Если что-то здесь упадёт ПОСЛЕ рефактора — рефактор
изменил наблюдаемое поведение «кассы» (charge / idempotency / refuse).

Тест НЕ "чинит" код — он утверждает то, что код РЕАЛЬНО делает сейчас.

Выбранные actions (2026-07-29 — переехали, см. константу CHARGE_ACTION ниже):
    - CHARGE_ACTION = hero.detach_hold  price=30  — денежные блоки. Не
      backend-only (значит есть строка в module_actions), без серверных гейтов
      и кулдаунов, требует живого героя — герой alice засеян в `_build_db`.
    - hero.create   price=0  — freebie-путь. Требует, чтобы героя ещё НЕ было,
      поэтому идёт на отдельного зрителя carol.
    - RETIRED_ACTION = player.respawn — блок [9]: убранное из продажи не
      покупается. Раньше касса характеризовалась ИМ, и уборка из продажи
      положила тест на полдня незамеченным.

Пересечение «покупаемое ∩ есть цена ∩ не требует героя» опустело: проверено
программно 29.07 — из трёх действий без требования героя hero.create бесплатен,
player.respawn снят с продажи, tournament.predict backend-only. Поэтому герой
теперь засевается, а не появляется в середине прогона.

Роль: request без X-Twitch-JWT + без client в ASGI-scope → verify_twitch_jwt
возвращает {"status":"none"} → роль "viewer" → price_mult=1.0 (чистый baseline,
без broadcaster-скидки даже в DEV_MODE — client=None не localhost).
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import traceback
from pathlib import Path

# Windows console (cp1251) не умеет emoji — переключаем stdout/stderr на UTF-8.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

# Setup imports — script запускается из backend/, добавляем его в path
HERE = Path(__file__).parent.absolute()
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))

# Required env vars для config.py / migrations.
os.environ.setdefault("TWITCH_OAUTH_TOKEN", "oauth:test")
os.environ.setdefault("TWITCH_CLIENT_ID", "test_client")
os.environ.setdefault("TWITCH_CLIENT_SECRET", "test_secret")
os.environ.setdefault("TWITCH_BOT_ID", "test_bot")
os.environ.setdefault("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab")
os.environ.setdefault("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890")
os.environ.setdefault("ADMIN_PASSWORD", "test_admin_password_for_tests_only")
# M1 migration backfill'ит channel_id существующим строкам из TWITCH_BROADCASTER_ID.
# Должно быть числом, иначе m1_multitenant.apply() бросит RuntimeError.
os.environ.setdefault("TWITCH_BROADCASTER_ID", "98319857")

CHANNEL_ID = 98319857  # == TWITCH_BROADCASTER_ID (совпадение с M1-backfill default)
START_POINTS = 100_000

# ─────────────────────────────────────────────────────────────────────────────
# Действие, на котором характеризуется КАССА. Вынесено в константу намеренно.
#
# 2026-07-29: тест лежал красным (17 провалов) полдня, потому что здесь был
# зашит `player.respawn`, а его убрали из продажи — механики нет, решение
# правильное. Тест этого не заметил и «сломался» вместе с ней, причём имя
# действия было размазано по 14 местам. Теперь замена — правка одной строки.
#
# Требования к кандидату (проверять при замене!):
#   • в `_PURCHASABLE_ACTIONS` и в `ACTION_PRICES_DEFAULT` с ценой > 0;
#   • НЕ в `_BACKEND_ONLY_ACTIONS` (иначе не будет строки в module_actions);
#   • нет своей цены в `_ACTIONS_WITH_OWN_PRICING` (иначе цена не та);
#   • **нет кулдауна в `ACTION_COOLDOWNS_SEC`** — иначе второй вызов подряд
#     отказывает «способность на перезарядке», и тест кассы падает на чужой
#     логике. На это уже наступили: первым кандидатом был `hero.detach_hold`,
#     у него CD = 1с, и блоки идемпотентности/рефанда легли.
#   • серверные гейты допустимы, только если тест умеет их удовлетворить.
#
# Проверено программно 29.07: покупаемых, платных, не backend-only и БЕЗ
# кулдауна во всём Bannerlord осталось **два** — `hero.army_create` и
# `hero.reforge_quality`. Взят первый: его гейты (королевство + лидер клана +
# не в армии) уже разбираются блоком [8], то есть способ их выставить известен
# и проверен. Состояние героя под них засевается в `_build_db`.
CHARGE_ACTION = "hero.army_create"
CHARGE_PRICE = 1000

# Действие, убранное из продажи. Тест закрепляет, что оно НЕ покупается —
# чтобы следующая уборка не осталась незамеченной, как случилось с respawn.
RETIRED_ACTION = "player.respawn"


# ─────────────────────────────────────────────────────────────────────────────
# Test runner — minimal без pytest
# ─────────────────────────────────────────────────────────────────────────────
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


def assert_true(cond: bool, label: str):
    if cond:
        _successes.append(label)
        print(f"  ✅ {label}")
    else:
        msg = f"  ❌ {label}: expected truthy"
        _failures.append(msg)
        print(msg)


def assert_false(cond: bool, label: str):
    assert_true(not cond, label)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers — фейковый Request + DB-инспекция
# ─────────────────────────────────────────────────────────────────────────────
def _make_anon_request():
    """Минимальный starlette.requests.Request без X-Twitch-JWT и без client.

    verify_twitch_jwt(request):
      - DEV_MODE-ветка читает request.client.host; client=None → "" → не
        localhost → bypass НЕ выдаётся (даже если DEV_MODE=true).
      - Дальше request.headers.get("X-Twitch-JWT") → "" → {"status":"none"}.
    Итог — роль "viewer", price_mult=1.0. Чистый baseline.
    """
    from starlette.requests import Request
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/bannerlord/action",
        "headers": [],   # никаких заголовков → нет X-Twitch-JWT
        "query_string": b"",
        # намеренно НЕТ ключа "client" → request.client == None
    }
    return Request(scope)


async def _get_points(db, channel_id: int, username: str):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT points FROM viewers WHERE channel_id=? AND username=?",
            (channel_id, username))
        row = await cur.fetchone()
    return (row[0] if row else None)


async def _set_points(db, channel_id: int, username: str, points: int):
    async with db._connect() as conn:
        await conn.execute(
            "UPDATE viewers SET points=? WHERE channel_id=? AND username=?",
            (points, channel_id, username))
        await conn.commit()


async def _count_actions(db, channel_id: int, action_type: str):
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM module_actions "
            "WHERE channel_id=? AND module_id='bannerlord' AND type=?",
            (channel_id, action_type))
        row = await cur.fetchone()
    return row[0]


# ─────────────────────────────────────────────────────────────────────────────
# DB setup — реальный Database + полная схема через main.run_migrations()
# ─────────────────────────────────────────────────────────────────────────────
async def _build_db(db_path: str):
    """Поднимает изолированную БД с ПОЛНОЙ схемой (init_tables + все миграции).

    main.run_migrations() ссылается на module-global `main.db`, поэтому
    подменяем его на наш temp Database ПЕРЕД вызовом. dependencies.set_db()
    тоже указываем на него — функция под тестом читает БД через get_db().
    """
    import main  # импорт безопасен: BotCore.__init__ in-memory, пул не открыт
    import dependencies
    from database import Database

    test_db = Database(db_path)
    main.db = test_db            # run_migrations() использует global `db`
    dependencies.set_db(test_db)  # get_db() в коде под тестом → наш db

    await test_db.init_pool()
    await test_db.init_tables()
    await main.run_migrations()

    # Test channel + viewer. После M1 viewers имеет channel_id + UNIQUE(channel_id, username).
    async with test_db._connect() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO channels (channel_id, login, display_name, tier) "
            "VALUES (?, 'alice_chan', 'Alice Channel', 'free')",
            (CHANNEL_ID,))
        await conn.execute(
            "INSERT INTO viewers (channel_id, username, points) VALUES (?, 'alice', ?)",
            (CHANNEL_ID, START_POINTS))
        # carol — зритель БЕЗ героя. Нужен блоку [5]: `hero.create` требует,
        # чтобы живого героя ещё не было, а у alice он теперь есть с самого
        # начала (см. ниже).
        await conn.execute(
            "INSERT INTO viewers (channel_id, username, points) VALUES (?, 'carol', ?)",
            (CHANNEL_ID, START_POINTS))
        # Герой alice засеян СРАЗУ. Касса требует живого героя для всего, кроме
        # трёх действий из `_ACTIONS_WITHOUT_HERO_REQUIREMENT`, и среди них не
        # осталось ни одного ПЛАТНОГО (проверено 29.07: hero.create бесплатен,
        # player.respawn убран из продажи, tournament.predict backend-only).
        # Поэтому денежные блоки идут на обычном действии, а герой нужен им
        # с первой строки — раньше он появлялся только в блоке [6].
        # Состояние под гейты CHARGE_ACTION (hero.army_create): королевство есть,
        # alice — лидер клана, в армии не состоит. Блок [8] потом сам гоняет эти
        # гейты по своим сценариям — он последний из тех, кто их трогает.
        import json as _json
        await conn.execute(
            "INSERT OR IGNORE INTO bannerlord_heroes "
            "(channel_id, username, hero_id, display_name, is_alive, is_prisoner, gold, "
            " kingdom_info_json, party_info_json) "
            "VALUES (?, 'alice', 'test_hero_alice', 'Alice Hero', 1, 0, 500000, ?, ?)",
            (CHANNEL_ID,
             _json.dumps({"id": "vlandia", "name": "Vlandia", "is_clan_leader": True}),
             _json.dumps({"in_army": False})))
        await conn.commit()

    return test_db


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────
async def test_happy_path_charge(db, buy):
    """1. Happy path: CHARGE_ACTION списывает РОВНО свою цену + enqueue."""
    print(f"\n[1] Happy path charge — {CHARGE_ACTION} (price={CHARGE_PRICE})")
    await _set_points(db, CHANNEL_ID, "alice", START_POINTS)

    before = await _get_points(db, CHANNEL_ID, "alice")
    actions_before = await _count_actions(db, CHANNEL_ID, CHARGE_ACTION)

    res = await buy(
        _make_anon_request(), "alice", CHANNEL_ID, CHARGE_ACTION,
        {"client_action_id": "happy-charge-1"})

    assert_eq(res.get("success"), True, "result.success is True")
    assert_eq(res.get("charged"), CHARGE_PRICE,
              f"result.charged == {CHARGE_PRICE} (server-side price)")
    assert_eq(res.get("perk"), "viewer", "role resolved to 'viewer' (no JWT)")
    assert_eq(res.get("perk_price_mult"), 1.0, "viewer → price_mult 1.0 (no discount)")
    assert_true(bool(res.get("action_id")), "result has an action_id (enqueued)")

    after = await _get_points(db, CHANNEL_ID, "alice")
    assert_eq(before - after, CHARGE_PRICE, f"points dropped by EXACTLY {CHARGE_PRICE}")

    actions_after = await _count_actions(db, CHANNEL_ID, CHARGE_ACTION)
    assert_eq(actions_after - actions_before, 1,
              "exactly 1 module_actions row enqueued (action NOT backend-only)")


async def test_idempotency(db, buy):
    """2. Idempotency: тот же client_action_id дважды → charge ОДИН раз."""
    print("\n[2] Idempotency — same client_action_id twice charges once")
    await _set_points(db, CHANNEL_ID, "alice", START_POINTS)

    cid = "idem-charge-xyz"
    before = await _get_points(db, CHANNEL_ID, "alice")

    res1 = await buy(_make_anon_request(), "alice", CHANNEL_ID,
                     CHARGE_ACTION, {"client_action_id": cid})
    mid = await _get_points(db, CHANNEL_ID, "alice")

    res2 = await buy(_make_anon_request(), "alice", CHANNEL_ID,
                     CHARGE_ACTION, {"client_action_id": cid})
    after = await _get_points(db, CHANNEL_ID, "alice")

    assert_eq(res1.get("success"), True, "first call succeeds")
    assert_eq(before - mid, CHARGE_PRICE, f"first call charged {CHARGE_PRICE}")

    assert_eq(res2.get("success"), True, "replay call still success=True")
    assert_eq(res2.get("idempotent_replay"), True,
              "replay response flagged idempotent_replay=True")
    assert_eq(res2.get("action_id"), res1.get("action_id"),
              "replay returns the SAME action_id as the first call")
    assert_eq(mid - after, 0, "second call did NOT charge again (points unchanged)")
    assert_eq(before - after, CHARGE_PRICE,
              f"net charge across both calls == {CHARGE_PRICE} (charged once)")

    # И ровно одна строка в outbox для этого client_action_id.
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM module_actions "
            "WHERE channel_id=? AND module_id='bannerlord' AND client_action_id=?",
            (CHANNEL_ID, cid))
        n = (await cur.fetchone())[0]
    assert_eq(n, 1, "exactly 1 module_actions row for that client_action_id")


async def test_insufficient_funds(db, buy):
    """3. Insufficient funds: баланс < price → refuse, баланс НЕ меняется."""
    print("\n[3] Insufficient funds — refuse, no partial charge")
    # Баланс строго ниже цены действия.
    await _set_points(db, CHANNEL_ID, "alice", CHARGE_PRICE - 1)
    before = await _get_points(db, CHANNEL_ID, "alice")
    actions_before = await _count_actions(db, CHANNEL_ID, CHARGE_ACTION)

    res = await buy(_make_anon_request(), "alice", CHANNEL_ID, CHARGE_ACTION,
                    {"client_action_id": "poor-charge-1"})

    assert_eq(res.get("success"), False, "result.success is False (can't afford)")
    msg = (res.get("message") or "").lower()
    assert_true("недостаточно" in msg, "refusal message mentions 'недостаточно'")

    after = await _get_points(db, CHANNEL_ID, "alice")
    assert_eq(after, before, "points UNCHANGED (no partial charge)")
    actions_after = await _count_actions(db, CHANNEL_ID, CHARGE_ACTION)
    assert_eq(actions_after, actions_before, "no module_actions row enqueued on refusal")


async def test_unknown_action_refused(db, buy):
    """4. Unknown action: не в _PURCHASABLE_ACTIONS → refuse, ничего не списано."""
    print("\n[4] Unknown action — purchasable-whitelist guard")
    await _set_points(db, CHANNEL_ID, "alice", START_POINTS)
    before = await _get_points(db, CHANNEL_ID, "alice")

    res = await buy(_make_anon_request(), "alice", CHANNEL_ID,
                    "hero.totally_fake_action",
                    {"client_action_id": "fake-1"})

    assert_eq(res.get("success"), False, "unknown action refused (success False)")
    msg = (res.get("message") or "").lower()
    assert_true("не разрешён" in msg, "message says action 'не разрешён'")
    after = await _get_points(db, CHANNEL_ID, "alice")
    assert_eq(after, before, "balance untouched for refused unknown action")


async def test_free_action_no_charge(db, buy):
    """5. Freebie sanity: hero.create (price=0) → success, 0 списано, enqueue.

    Характеризует поведение price=0 пути (charge-блок пропускается). hero.create
    требует, чтобы живого героя ещё НЕ было — поэтому идёт на carol: у alice
    герой засеян с самого начала (нужен денежным блокам).
    """
    print("\n[5] Free action sanity — hero.create (price=0), зритель carol")
    await _set_points(db, CHANNEL_ID, "carol", START_POINTS)
    before = await _get_points(db, CHANNEL_ID, "carol")

    res = await buy(_make_anon_request(), "carol", CHANNEL_ID, "hero.create",
                    {"client_action_id": "create-1"})

    assert_eq(res.get("success"), True, "hero.create succeeds")
    assert_eq(res.get("charged"), 0, "charged == 0 (free)")
    after = await _get_points(db, CHANNEL_ID, "carol")
    assert_eq(before - after, 0, "no crustics spent on free action")
    n = await _count_actions(db, CHANNEL_ID, "hero.create")
    assert_eq(n, 1, "hero.create enqueued (NOT backend-only)")


async def test_power_activate_per_power_price(db, buy):
    """6. power.activate списывает PER-POWER цену (POWER_PRICES), НЕ flat 50.

    Регрессия на баг 2026-06-14: power.activate сидел в ACTION_PRICES_DEFAULT
    (flat 50) → бэк списывал 50 за ЛЮБУЮ активку, а фронт показывал 100–350
    ("написано одно, списано другое"). Фикс: per-power цена enforced server-side
    в _prepare_action из POWER_PRICES; неизвестный power_key → refuse.
    """
    print("\n[6] power.activate — per-power price (POWER_PRICES), not flat 50")
    # power.activate требует живого героя — создаём минимального.
    async with db._connect() as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO bannerlord_heroes "
            "(channel_id, username, hero_id, display_name) "
            "VALUES (?, 'alice', 'hero_alice', 'Alice Hero')",
            (CHANNEL_ID,))
        await conn.commit()
    await _set_points(db, CHANNEL_ID, "alice", START_POINTS)

    # rage → 300 (POWER_PRICES["rage"]), НЕ старые flat 50.
    before = await _get_points(db, CHANNEL_ID, "alice")
    res = await buy(_make_anon_request(), "alice", CHANNEL_ID, "power.activate",
                    {"power_key": "rage", "client_action_id": "pow-rage-1"})
    assert_eq(res.get("success"), True, "power.activate(rage) succeeds")
    assert_eq(res.get("charged"), 300, "rage charged 300 (per-power, NOT flat 50)")
    after = await _get_points(db, CHANNEL_ID, "alice")
    assert_eq(before - after, 300, "points dropped by EXACTLY 300 for rage")

    # heal_burst → 100 (другая цена → доказывает per-power, не константа).
    before2 = await _get_points(db, CHANNEL_ID, "alice")
    res2 = await buy(_make_anon_request(), "alice", CHANNEL_ID, "power.activate",
                     {"power_key": "heal_burst", "client_action_id": "pow-heal-1"})
    assert_eq(res2.get("charged"), 100, "heal_burst charged 100 (different per-power price)")
    after2 = await _get_points(db, CHANNEL_ID, "alice")
    assert_eq(before2 - after2, 100, "points dropped by EXACTLY 100 for heal_burst")

    # Неизвестная активка → refuse, ничего не списано (security gate).
    before3 = await _get_points(db, CHANNEL_ID, "alice")
    res3 = await buy(_make_anon_request(), "alice", CHANNEL_ID, "power.activate",
                     {"power_key": "totally_fake_power", "client_action_id": "pow-fake-1"})
    assert_eq(res3.get("success"), False, "unknown power_key refused")
    msg = (res3.get("message") or "").lower()
    assert_true("не найдена" in msg, "refusal message mentions 'не найдена'")
    after3 = await _get_points(db, CHANNEL_ID, "alice")
    assert_eq(after3, before3, "balance untouched for unknown power")


async def test_refund_on_ack_failure(db, buy):
    """7. Refund на отказ мода (#21): action.failed → крустики назад, idempotent.

    Воспроизводит путь, который теперь дёргает module_ack при success=false:
    синтетический action.failed → adapter.handle_event → _on_action_failed →
    atomic refund (idempotent через REFUNDED: маркер). Двойной вызов = ОДИН возврат.
    """
    print("\n[7] Refund on mod-refuse (#21) — action.failed returns crustics, idempotent")
    from modules._loader import discover_modules, get_module
    from modules._base import ModuleEnvelope
    discover_modules()
    adapter = get_module("bannerlord")
    assert_true(adapter is not None, "bannerlord adapter discovered")
    if adapter is None:
        return

    await _set_points(db, CHANNEL_ID, "alice", START_POINTS)
    before = await _get_points(db, CHANNEL_ID, "alice")

    # Charge: CHARGE_ACTION → enqueue module_actions row с price+initiated_by.
    res = await buy(_make_anon_request(), "alice", CHANNEL_ID, CHARGE_ACTION,
                    {"client_action_id": "refund-charge-1"})
    action_id = res.get("action_id")
    assert_eq(res.get("charged"), CHARGE_PRICE, f"charged {CHARGE_PRICE} before refund")
    mid = await _get_points(db, CHANNEL_ID, "alice")
    assert_eq(before - mid, CHARGE_PRICE, f"points dropped {CHARGE_PRICE} after charge")

    # Мод отказал → action.failed (ровно то, что роутит module_ack при success=false).
    env = ModuleEnvelope(id=action_id, kind="event", type="action.failed", ts=0,
                         data={"action_id": action_id, "reason": "test_refuse"})
    await adapter.handle_event(CHANNEL_ID, env)
    after = await _get_points(db, CHANNEL_ID, "alice")
    assert_eq(after - mid, CHARGE_PRICE, f"refund credited exactly {CHARGE_PRICE}")
    assert_eq(after, before, "points fully restored (back to START)")

    # Idempotent: повторный action.failed (или поздний реальный event) → НЕ двойной refund.
    await adapter.handle_event(CHANNEL_ID, env)
    after2 = await _get_points(db, CHANNEL_ID, "alice")
    assert_eq(after2, after, "second action.failed does NOT double-refund (idempotent)")


async def test_army_create_server_gates(db, buy):
    """8. hero.army_create — server-side гейты (Army MVP).

    Гейт зеркалит C# CreateArmyHandler: королевство + лидер клана + не в армии.
    До фикса бэк списывал 1000💎 любому (гейт был только в моде) → зритель
    без клана платил и ждал mod-refuse+refund роундтрип. Теперь refuse ДО commit.
    Требует героя alice — создан в тесте [6].
    """
    print("\n[8] hero.army_create — server gates (kingdom + clan leader + not in army)")
    import json as _json

    async def _set_hero_state(kingdom_info, party_info):
        async with db._connect() as conn:
            await conn.execute(
                "UPDATE bannerlord_heroes SET kingdom_info_json=?, party_info_json=? "
                "WHERE channel_id=? AND username='alice'",
                (_json.dumps(kingdom_info) if kingdom_info else None,
                 _json.dumps(party_info) if party_info else None,
                 CHANNEL_ID))
            await conn.commit()

    # (a) Нет королевства → refuse, баланс цел, outbox пуст (ROLLBACK).
    await _set_points(db, CHANNEL_ID, "alice", START_POINTS)
    await _set_hero_state(None, None)
    before = await _get_points(db, CHANNEL_ID, "alice")
    n_before = await _count_actions(db, CHANNEL_ID, "hero.army_create")
    res = await buy(_make_anon_request(), "alice", CHANNEL_ID, "hero.army_create",
                    {"client_action_id": "army-nokingdom-1"})
    assert_eq(res.get("success"), False, "no kingdom → refused")
    assert_true("королевства" in (res.get("message") or ""),
                "refusal message mentions королевство")
    assert_eq(await _get_points(db, CHANNEL_ID, "alice"), before,
              "balance untouched (no kingdom)")
    assert_eq(await _count_actions(db, CHANNEL_ID, "hero.army_create"), n_before,
              "no enqueue on refusal (ROLLBACK reverted outbox row)")

    # (b) Королевство есть, но НЕ лидер клана → refuse.
    await _set_hero_state(
        {"id": "vlandia", "name": "Vlandia", "is_clan_leader": False}, None)
    res = await buy(_make_anon_request(), "alice", CHANNEL_ID, "hero.army_create",
                    {"client_action_id": "army-notleader-1"})
    assert_eq(res.get("success"), False, "not clan leader → refused")
    assert_true("лидер клана" in (res.get("message") or ""),
                "refusal message mentions лидер клана")
    assert_eq(await _get_points(db, CHANNEL_ID, "alice"), before,
              "balance untouched (not clan leader)")

    # (c) Лидер клана, но уже в армии → refuse.
    await _set_hero_state(
        {"id": "vlandia", "name": "Vlandia", "is_clan_leader": True},
        {"in_army": True})
    res = await buy(_make_anon_request(), "alice", CHANNEL_ID, "hero.army_create",
                    {"client_action_id": "army-inarmy-1"})
    assert_eq(res.get("success"), False, "already in army → refused")
    assert_true("уже в армии" in (res.get("message") or ""),
                "refusal message mentions уже в армии")
    assert_eq(await _get_points(db, CHANNEL_ID, "alice"), before,
              "balance untouched (already in army)")

    # (d) Все гейты пройдены → success, charged 1000, enqueued ровно 1.
    await _set_hero_state(
        {"id": "vlandia", "name": "Vlandia", "is_clan_leader": True},
        {"in_army": False})
    res = await buy(_make_anon_request(), "alice", CHANNEL_ID, "hero.army_create",
                    {"client_action_id": "army-ok-1"})
    assert_eq(res.get("success"), True, "clan leader in kingdom → success")
    assert_eq(res.get("charged"), 1000, "charged exactly 1000 (ACTION_PRICES_DEFAULT)")
    after = await _get_points(db, CHANNEL_ID, "alice")
    assert_eq(before - after, 1000, "points dropped by EXACTLY 1000")
    assert_eq(await _count_actions(db, CHANNEL_ID, "hero.army_create"), n_before + 1,
              "exactly 1 hero.army_create enqueued for the mod")


async def test_retired_action_not_purchasable(db, buy):
    """9. Убранное из продажи НЕ покупается — и это закреплено тестом.

    Этот блок появился из-за самого себя. 2026-07-29 `player.respawn` убрали из
    продажи (механики нет — за ним была заглушка `EchoHandler`), и тест кассы,
    который был на нём построен, лёг красным на полдня незамеченным.

    Теперь у уборки есть страховка с двух сторон: действие обязано отсутствовать
    в списке покупаемого И отказывать в кассе, не списывая ничего. Если кто-то
    вернёт его в продажу не подумав — упадёт здесь, а не у зрителя в кошельке.
    """
    print(f"\n[9] Retired action — {RETIRED_ACTION} снят с продажи и не покупается")
    from routes.bannerlord import _PURCHASABLE_ACTIONS, ACTION_PRICES_DEFAULT

    assert_true(RETIRED_ACTION not in _PURCHASABLE_ACTIONS,
                f"{RETIRED_ACTION} НЕ в _PURCHASABLE_ACTIONS")
    assert_true(RETIRED_ACTION not in ACTION_PRICES_DEFAULT,
                f"{RETIRED_ACTION} НЕ в ACTION_PRICES_DEFAULT (цены нет)")

    await _set_points(db, CHANNEL_ID, "alice", START_POINTS)
    before = await _get_points(db, CHANNEL_ID, "alice")
    actions_before = await _count_actions(db, CHANNEL_ID, RETIRED_ACTION)

    res = await buy(_make_anon_request(), "alice", CHANNEL_ID, RETIRED_ACTION,
                    {"client_action_id": "retired-1"})

    assert_eq(res.get("success"), False, "покупка снятого действия отклонена")
    after = await _get_points(db, CHANNEL_ID, "alice")
    assert_eq(after, before, "баланс не тронут")
    assert_eq(await _count_actions(db, CHANNEL_ID, RETIRED_ACTION), actions_before,
              "команда моду НЕ поставлена")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
async def _run():
    db_path = tempfile.mktemp(suffix="_bnr_buy_test.db")
    db = await _build_db(db_path)
    # Импортируем функцию под тестом ПОСЛЕ set_db (она читает get_db() в рантайме).
    from routes.bannerlord import _bannerlord_buy_action_locked as buy

    try:
        await test_happy_path_charge(db, buy)
        await test_idempotency(db, buy)
        await test_insufficient_funds(db, buy)
        await test_unknown_action_refused(db, buy)
        await test_free_action_no_charge(db, buy)
        await test_power_activate_per_power_price(db, buy)
        await test_refund_on_ack_failure(db, buy)
        await test_army_create_server_gates(db, buy)
        await test_retired_action_not_purchasable(db, buy)
    finally:
        # Закрываем пул и удаляем temp-БД (реальную viewers.db НЕ трогаем).
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
    print("CHARACTERIZATION: _bannerlord_buy_action_locked (Bannerlord касса)")
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
    print("ALL GREEN ✅ — текущее поведение кассы зафиксировано.")
    sys.exit(0)


if __name__ == "__main__":
    main()
