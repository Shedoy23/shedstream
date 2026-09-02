# -*- coding: utf-8 -*-
"""routes/tugofwar.py — «Канат»: дуэль 1 на 1 с рейтингом и сезоном.

Заменяет кубики (решение владельца 2026-09-01). Устроена ПО ПРИНЦИПУ ОСТАЛЬНЫХ
игр — крестиков и дуэлей: очередь подбора, комната на двоих, ELO, сезон и призы
топ-3. Командный вариант был написан в тот же день и по решению владельца убран:
«не нужен командный, по принципу остальных с сезонами».

## Почему 1v1 важен именно для наград

В командном канате приз нельзя было вешать на исход: «выбрал сторону → исход
зависит не от тебя → получил валюту» читается как ставка
(`docs/specs/SPEC_TUG_OF_WAR_COMPLIANCE_JIM_2026-08-26.md`, блокер №1). В дуэли
исход целиком в руках двоих, поэтому сезонный приз по рейтингу стоит ровно на
той же почве, что у крестиков и дуэлей, — и это ровно тот довод, по которому
владелец выбирал путь ещё 26.08.

## Механика

Двое тянут один канат MATCH_SEC секунд. Цена n-го тапа — `max(TAP_MIN, TAP_BASE
− (n−1)×TAP_DECAY)`: долбить кнопку быстро смысла мало, выигрывает ровный темп и
терпение. Позиция каната — отношение `(A−B)÷(A+B)` в пределах ±ROPE_LIMIT, всё
целочисленно. По истечении времени сильнее натянувший побеждает, равенство —
ничья. **Случайности нет ни одной**: ни в подборе исхода, ни в разрешении
ничьей. Проверяется тестом грепом по модулю.

За отдельный матч крустики НЕ платятся — как и в крестиках. Платит только сезон:
топ-3 по рейтингу на закрытии, порог ELO тот же.

## Почему сезонные функции скопированы, а не «вынесены в общее»

В `check_season_end` крестиков сидят три исправленных инцидента: двойная выплата
без транзакции, незакрывающийся старый сезон и рождение второго живого сезона
поверх идущего. Общий модуль для четырёх игр — правильная уборка, но делать её
заодно с новой механикой значит рисковать всеми четырьмя сезонами сразу.
Копия сохраняет исправления дословно; вынос — отдельной задачей (`DEFERRED.md`).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Request

from dependencies import get_db, require_jwt_user, resolve_channel_id_or_default

router = APIRouter()
log = logging.getLogger("rimlink.tug")

_AUTH_FAIL = {"success": False, "message": "❌ Требуется авторизация Twitch"}

GAME_TYPE = "tug"

# ── Параметры. На сервере, а не во фронте: фронт замерзает на CDN Twitch до
#    следующего ревью, а эти числа входят в опубликованные правила матча.
MATCH_SEC = 45           # длительность дуэли
TAP_BASE = 100           # цена первого тапа
TAP_DECAY = 4            # насколько дешевеет каждый следующий
TAP_MIN = 20             # пол: ниже этого тап не опускается
TAPS_PER_REQUEST = 10    # больше за один запрос не принимаем
PULL_COOLDOWN_SEC = 0.8  # и не чаще, чем раз в столько секунд
ROPE_LIMIT = 10_000      # края каната: ±10000 = одна сторона тянет всё

ELO_START = 1000
ELO_K = 32
PRIZES = {1: 300_000, 2: 200_000, 3: 100_000}
PRIZE_ELO_GATE = 1100


def _rules() -> dict:
    """Правила матча одним объектом — фронт печатает, не вычисляет."""
    return {
        "match_sec": MATCH_SEC,
        "tap_base": TAP_BASE,
        "tap_decay": TAP_DECAY,
        "tap_min": TAP_MIN,
        "rope_limit": ROPE_LIMIT,
        "prizes": PRIZES,
        "prize_elo_gate": PRIZE_ELO_GATE,
        "match_reward": 0,
        "formula_ru": (
            f"Дуэль длится {MATCH_SEC} секунд. n-й тап стоит "
            f"max({TAP_MIN}, {TAP_BASE} − (n−1)×{TAP_DECAY}) очков — долбить "
            "быстро смысла мало, выигрывает ровный темп. Канат показывает, "
            "насколько один вклад больше другого: (A−B)÷(A+B). Кто натянул "
            "сильнее к концу времени, тот и выиграл; поровну — ничья, "
            "победитель не разыгрывается."
        ),
        "reward_ru": (
            "Участие бесплатное, за отдельный матч крустики не начисляются. "
            f"Платит сезон: топ-3 по рейтингу получают {PRIZES[1]:,}💎 / "
            f"{PRIZES[2]:,}💎 / {PRIZES[3]:,}💎 при рейтинге не ниже "
            f"{PRIZE_ELO_GATE}."
        ).replace(",", " "),
    }


def _tap_value(tap_index: int) -> int:
    """Цена тапа по счёту (1-based). Целые числа, никакой случайности."""
    return max(TAP_MIN, TAP_BASE - (tap_index - 1) * TAP_DECAY)


def _batch_value(already: int, taps: int) -> int:
    """Сколько очков дадут `taps` тапов, если до них уже было `already`."""
    return sum(_tap_value(already + i + 1) for i in range(taps))


def _rope_pos(eff_a: int, eff_b: int) -> int:
    """Позиция каната: ОТНОСИТЕЛЬНОЕ преимущество, ±ROPE_LIMIT.

    Отношение, а не разность. Первая (командная) редакция считала разность, и
    канат улетал за отметку от первой же пачки тапов: разность нормированного
    вклада ничем не ограничена. Позиция обязана показывать, НАСКОЛЬКО один
    сильнее другого, а не сколько всего натянули.
    """
    total = eff_a + eff_b
    if total <= 0:
        return 0
    pos = ((eff_a - eff_b) * ROPE_LIMIT) // total
    return max(-ROPE_LIMIT, min(ROPE_LIMIT, pos))


def _elo_update(rating: int, opp_rating: int, result: float) -> int:
    expected = 1 / (1 + 10 ** ((opp_rating - rating) / 400))
    return round(rating + ELO_K * (result - expected))


# ─── Сезон: копия проверенной логики крестиков под game_type='tug' ────────────

def _next_season_end():
    now = datetime.now(timezone.utc)
    days_ahead = (6 - now.weekday()) % 7
    days_ahead = 14 if days_ahead == 0 else days_ahead + 7
    target = now + timedelta(days=days_ahead)
    return target.replace(hour=0, minute=0, second=0, microsecond=0)


async def _ensure_season(conn, channel_id: int) -> int:
    row = await (await conn.execute(
        "SELECT id FROM duel_seasons WHERE channel_id = ? AND game_type = ? "
        "AND finished = 0 ORDER BY id DESC LIMIT 1",
        (channel_id, GAME_TYPE))).fetchone()
    if row:
        return row[0]
    now = datetime.now(timezone.utc)
    await conn.execute(
        "INSERT INTO duel_seasons (channel_id, game_type, started_at, ends_at, finished) "
        "VALUES (?, ?, ?, ?, 0)",
        (channel_id, GAME_TYPE, now.isoformat(), _next_season_end().isoformat()))
    return (await (await conn.execute("SELECT last_insert_rowid()")).fetchone())[0]


async def _get_or_init_stats(conn, channel_id: int, username: str, season_id: int):
    row = await (await conn.execute(
        "SELECT elo, win_streak FROM duel_stats "
        "WHERE channel_id = ? AND username = ? AND game_type = ?",
        (channel_id, username.lower(), GAME_TYPE))).fetchone()
    if row:
        return row[0], row[1]
    await conn.execute(
        "INSERT OR IGNORE INTO duel_stats "
        "(channel_id, username, game_type, elo, win_streak, season_id) "
        "VALUES (?, ?, ?, ?, 0, ?)",
        (channel_id, username.lower(), GAME_TYPE, ELO_START, season_id))
    return ELO_START, 0


async def _update_stats(conn, channel_id: int, username: str, elo: int, streak: int):
    await conn.execute(
        "UPDATE duel_stats SET elo = ?, win_streak = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE channel_id = ? AND username = ? AND game_type = ?",
        (elo, streak, channel_id, username.lower(), GAME_TYPE))


async def check_season_end(channel_id: int = None):
    """Закрыть просроченный сезон, выдать призы топ-3, начать новый.

    Копия `routes/tictactoe.py:check_season_end` с game_type='tug'. В ней три
    исправленных инцидента, и переписывать их «покрасивее» здесь нельзя:
    транзакция против двойной выплаты, разбор ВСЕХ незакрытых сезонов и запрет
    рождать новый сезон поверх живого.
    """
    cid = channel_id if channel_id else resolve_channel_id_or_default()
    db = get_db()
    async with db._connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        rows = await (await conn.execute(
            "SELECT id, ends_at FROM duel_seasons "
            "WHERE channel_id = ? AND game_type = ? AND finished = 0 ORDER BY id ASC",
            (cid, GAME_TYPE))).fetchall()
        if not rows:
            await _ensure_season(conn, cid)
            await conn.commit()
            return

        now_utc = datetime.now(timezone.utc)
        expired = []
        for r_id, r_ends in rows:
            r_end = datetime.fromisoformat(r_ends)
            if r_end.tzinfo is None:
                r_end = r_end.replace(tzinfo=timezone.utc)
            if now_utc >= r_end:
                expired.append(r_id)
        if not expired:
            await conn.commit()
            return

        live = [r_id for r_id, _ in rows if r_id not in expired]
        for stale_id in expired[:-1]:
            await conn.execute(
                "UPDATE duel_seasons SET finished = 1 WHERE channel_id = ? AND id = ?",
                (cid, stale_id))
            log.info("[TUG-SEASON] ch=%s: сезон #%s закрыт без призов", cid, stale_id)
        season_id = expired[-1]

        top = await (await conn.execute(
            "SELECT username, elo FROM duel_stats "
            "WHERE channel_id = ? AND game_type = ? AND season_id = ? AND elo >= ? "
            "ORDER BY elo DESC LIMIT 3",
            (cid, GAME_TYPE, season_id, PRIZE_ELO_GATE))).fetchall()
        for rank, (uname, elo) in enumerate(top, 1):
            prize = PRIZES.get(rank, 0)
            if not prize:
                continue
            # Выплата и закрытие сезона — ОДНОЙ транзакцией. Иначе падение между
            # ними оставляет сезон незакрытым при выданных призах, и следующий
            # проход платит второй раз (инцидент 2026-07-30 в крестиках).
            await db.add_points_tx(conn, uname, prize, cid)
            await conn.execute(
                "INSERT INTO duel_season_payouts "
                "(channel_id, season_id, game_type, username, rank, elo, amount) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cid, season_id, GAME_TYPE, uname, rank, elo, prize))
            log.info("[TUG-SEASON] ch=%s #%s @%s (%s ELO) +%s💎",
                     cid, rank, uname, elo, prize)

        await conn.execute("UPDATE duel_seasons SET finished = 1 WHERE id = ?", (season_id,))
        if live:
            await conn.commit()
            return
        now = datetime.now(timezone.utc)
        await conn.execute(
            "INSERT INTO duel_seasons (channel_id, game_type, started_at, ends_at, finished) "
            "VALUES (?, ?, ?, ?, 0)",
            (cid, GAME_TYPE, now.isoformat(), _next_season_end().isoformat()))
        new_season_id = (await (await conn.execute("SELECT last_insert_rowid()")).fetchone())[0]

        # 2026-09-02: СБРОС рейтингов на новый сезон. Строки не было — я
        # «дословно копировал» логику крестиков и потерял ровно её. Без сброса
        # рейтинг копится через сезоны: топ-3 замирает на первых игроках, и приз
        # каждый сезон уходит одним и тем же, а новичок не догонит никогда.
        # Тест этого не поймал, потому что проверял ОДНО закрытие сезона, а не
        # следующий за ним. Класс: «скопировал форму, потерял часть содержимого».
        await conn.execute(
            "UPDATE duel_stats SET elo = ?, win_streak = 0, season_id = ? "
            "WHERE channel_id = ? AND game_type = ?",
            (ELO_START, new_season_id, cid, GAME_TYPE))
        await conn.commit()


# ─── Комната дуэли ────────────────────────────────────────────────────────────

def _fresh_state() -> dict:
    return {"ends_at": time.time() + MATCH_SEC,
            "taps": {"a": 0, "b": 0}, "eff": {"a": 0, "b": 0}, "last": {"a": 0.0, "b": 0.0}}


def _public_room(room_id: str, p_a: str, p_b: str, state: dict, status: str,
                 uname: str, outcome: Optional[str]) -> dict:
    side = "a" if uname == p_a else "b"
    return {
        "room_id": room_id,
        "opponent": p_b if side == "a" else p_a,
        "my_side": side,
        "pos": _rope_pos(state["eff"]["a"], state["eff"]["b"]),
        "my_taps": state["taps"][side],
        "seconds_left": max(0, int(state["ends_at"] - time.time())),
        "status": status,
        "outcome": outcome,
    }


async def _load_active_room(conn, channel_id: int, uname: str):
    cur = await conn.execute(
        "SELECT room_id, player_a, player_b, player_a_elo, player_b_elo, state, status, outcome "
        "FROM match_rooms WHERE channel_id = ? AND game_type = ? "
        "AND (player_a = ? OR player_b = ?) ORDER BY rowid DESC LIMIT 1",
        (channel_id, GAME_TYPE, uname, uname))
    return await cur.fetchone()


async def _finalize(conn, db, channel_id: int, room_id: str, p_a: str, p_b: str,
                    elo_a: int, elo_b: int, state: dict) -> str:
    """Подвести итог матча: победитель, ELO, серия. Ничья остаётся ничьёй."""
    eff_a, eff_b = state["eff"]["a"], state["eff"]["b"]
    if eff_a > eff_b:
        outcome, winner, res_a = "win_a", p_a, 1.0
    elif eff_b > eff_a:
        outcome, winner, res_a = "win_b", p_b, 0.0
    else:
        outcome, winner, res_a = "draw", None, 0.5

    new_elo_a = _elo_update(elo_a, elo_b, res_a)
    new_elo_b = _elo_update(elo_b, elo_a, 1.0 - res_a)
    await conn.execute(
        "UPDATE match_rooms SET state = ?, status = 'finished', winner = ?, "
        "outcome = ?, player_a_elo = ?, player_b_elo = ?, "
        "finished_at = CURRENT_TIMESTAMP WHERE room_id = ?",
        (json.dumps(state), winner, outcome, new_elo_a, new_elo_b, room_id))

    season_id = await _ensure_season(conn, channel_id)
    _, a_streak = await _get_or_init_stats(conn, channel_id, p_a, season_id)
    _, b_streak = await _get_or_init_stats(conn, channel_id, p_b, season_id)
    if outcome == "win_a":
        a_streak, b_streak = a_streak + 1, 0
    elif outcome == "win_b":
        a_streak, b_streak = 0, b_streak + 1
    await _update_stats(conn, channel_id, p_a, new_elo_a, a_streak)
    await _update_stats(conn, channel_id, p_b, new_elo_b, b_streak)
    log.info("[TUG] ch=%s room=%s итог=%s (%s против %s)",
             channel_id, room_id, outcome, eff_a, eff_b)
    return outcome


async def status_for(uname: str, channel_id: int) -> dict:
    """Состояние моего матча + правила + таблица сезона.

    Отделено от HTTP-обёртки намеренно: тесты бьют сюда. Гейт, который нельзя
    прогнать тестом, — это гейт, про который узнают в эфире.
    """
    db = get_db()
    async with db._connect() as conn:
        row = await _load_active_room(conn, channel_id, uname)
        room = None
        if row:
            room_id, p_a, p_b, elo_a, elo_b, state_json, status, outcome = row
            try:
                state = json.loads(state_json) if state_json else {}
            except Exception:
                state = {}
            if status == "active":
                if not state.get("ends_at"):
                    state = _fresh_state()
                    await conn.execute("UPDATE match_rooms SET state = ? WHERE room_id = ?",
                                       (json.dumps(state), room_id))
                if time.time() >= state["ends_at"]:
                    outcome = await _finalize(conn, db, channel_id, room_id,
                                              p_a, p_b, elo_a, elo_b, state)
                    status = "finished"
                await conn.commit()
            if state.get("ends_at"):
                room = _public_room(room_id, p_a, p_b, state, status, uname, outcome)

        cur = await conn.execute(
            "SELECT username, elo FROM duel_stats WHERE channel_id = ? AND game_type = ? "
            "ORDER BY elo DESC LIMIT 10", (channel_id, GAME_TYPE))
        board = [{"username": u, "elo": e} for u, e in await cur.fetchall()]
        cur2 = await conn.execute(
            "SELECT ends_at FROM duel_seasons WHERE channel_id = ? AND game_type = ? "
            "AND finished = 0 ORDER BY id DESC LIMIT 1", (channel_id, GAME_TYPE))
        srow = await cur2.fetchone()
    return {"success": True, "room": room, "rules": _rules(),
            "leaderboard": board, "season_ends_at": srow[0] if srow else None}


async def pull_rope(uname: str, channel_id: int, taps: int) -> dict:
    """Тянуть канат в своём матче. Бесплатно, крустики не списываются."""
    try:
        taps = int(taps)
    except (TypeError, ValueError):
        taps = 0
    taps = max(0, min(taps, TAPS_PER_REQUEST))
    if taps == 0:
        return {"success": False, "message": "Нечего тянуть"}

    now = time.time()
    db = get_db()
    async with db._connect() as conn:
        row = await _load_active_room(conn, channel_id, uname)
        if not row:
            return {"success": False, "message": "У тебя нет активного матча"}
        room_id, p_a, p_b, elo_a, elo_b, state_json, status, outcome = row
        if status != "active":
            return {"success": False, "message": "Матч уже завершён"}
        try:
            state = json.loads(state_json) if state_json else {}
        except Exception:
            state = {}
        if not state.get("ends_at"):
            state = _fresh_state()

        side = "a" if uname == p_a else "b"
        if now - float(state["last"].get(side) or 0) < PULL_COOLDOWN_SEC:
            return {"success": False, "message": "Слишком часто — тяни спокойнее"}

        if now >= state["ends_at"]:
            outcome = await _finalize(conn, db, channel_id, room_id,
                                      p_a, p_b, elo_a, elo_b, state)
            await conn.commit()
            return {"success": False, "message": "Время матча вышло",
                    "room": _public_room(room_id, p_a, p_b, state, "finished", uname, outcome)}

        gained = _batch_value(state["taps"][side], taps)
        state["taps"][side] += taps
        state["eff"][side] += gained
        state["last"][side] = now
        await conn.execute("UPDATE match_rooms SET state = ? WHERE room_id = ?",
                           (json.dumps(state), room_id))
        await conn.commit()
    return {"success": True, "gained": gained,
            "room": _public_room(room_id, p_a, p_b, state, "active", uname, None)}


# ── HTTP-обёртки. Тонкие намеренно: тут только авторизация и разбор тела. ──

@router.get("/api/tug/status")
async def http_status(request: Request):
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth
    try:
        await check_season_end(channel_id)
    except Exception as e:
        log.warning("[TUG] check_season_end ch=%s: %s", channel_id, e)
    return await status_for(username, channel_id)


@router.post("/api/tug/pull")
async def http_pull(request: Request):
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth
    try:
        body = await request.json()
    except Exception:
        body = {}
    return await pull_rope(username, channel_id, body.get("taps") or 0)
