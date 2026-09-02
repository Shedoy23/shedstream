# -*- coding: utf-8 -*-
"""routes/tugofwar.py — «Перетягивание каната»: массовая механика без случайности.

Заменяет кубики (решение владельца 2026-09-01). Кубики морозим: в них
случайность неустранима, и именно они стоят первыми в претензии Twitch по
правилу 3.5. Здесь броска нет НИ ОДНОГО — модуль не импортирует `random`, и это
проверяется тестом грепом, а не обещанием.

## Правила, которые видит зритель (и почему они именно такие)

Разбор комплаенса — `docs/specs/SPEC_TUG_OF_WAR_COMPLIANCE_JIM_2026-08-26.md`,
вердикт PASS-WITH-CHANGES. Четыре его блокера закрыты так:

1. **Награда не зависит от исхода.** Каждый, кто набрал минимум эффективных
   тапов, получает ОДИН И ТОТ ЖЕ фиксированный кредит за участие — и победитель,
   и проигравший, и ничья. Победившей стороне достаётся только статус (строка
   результата). Цепочка «выбрал сторону → исход зависит не от тебя → получил
   валюту» — это то, что читается как ставка, и её здесь нет.
2. **Случайности нет нигде.** Стороны выбирает зритель сам, авто-распределения
   нет; ничья остаётся ничьёй и не разыгрывается монеткой.
3. **Правила показываются ДО входа в раунд.** Все числа отдаёт `GET status` в
   поле `rules` — фронт их только печатает (CLAUDE.md, «Тонкий фронт»).
4. **Нормировка детерминирована и заморожена.** Размер команды фиксируется на
   закрытии приёма и дальше не меняется, вся математика целочисленная.

## Формула вклада (опубликована зрителю целиком)

n-й тап зрителя за раунд стоит `max(TAP_MIN, TAP_BASE - (n-1) * TAP_DECAY)`
очков. То есть частое долбление кнопки быстро упирается в пол, а спокойный темп
двигает канат почти так же — «без напряга» из спеки это не лозунг, а затухание.

Позиция каната: `pos = eff_a * SCALE / team_a - eff_b * SCALE / team_b`, целочисленно,
где `team_*` — замороженные размеры команд, а сама позиция — ОТНОШЕНИЕ
`(A−B)÷(A+B)` в пределах ±`ROPE_LIMIT`. Деление на размер команды и есть
«нормировка»: команда из двух человек не проигрывает автоматически команде из
двадцати. Досрочной победы нет — раунд всегда идёт до таймера.

## Жизненный цикл

`join` (приём) → `pull` (тяга) → `finished`. Переходы ЛЕНИВЫЕ — считаются при
любом чтении статуса, фонового цикла нет. Причина простая: фоновый цикл может
умереть молча, и мы это уже проходили (`tests/test_background_loops_survive.py`),
а ленивый переход не может — он либо посчитался, либо статус никто и не читал.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, Request

from dependencies import get_db, require_jwt_user

router = APIRouter()
log = logging.getLogger("rimlink.tugofwar")

_AUTH_FAIL = {"success": False, "message": "❌ Требуется авторизация Twitch"}

# ── Параметры. Здесь, а не во фронте: фронт замерзает на CDN Twitch до
#    следующего ревью, а эти числа входят в ОПУБЛИКОВАННЫЕ правила раунда.
JOIN_SEC = 20            # приём заявок
PULL_SEC = 90            # сама тяга
TAP_BASE = 100           # цена первого тапа
TAP_DECAY = 4            # насколько дешевеет каждый следующий
TAP_MIN = 20             # пол: ниже этого тап не опускается
TAPS_PER_REQUEST = 10    # больше за один запрос не принимаем
PULL_COOLDOWN_SEC = 0.8  # и не чаще, чем раз в столько секунд
SCALE = 1000             # множитель целочисленной нормировки
ROPE_LIMIT = 10_000      # края каната: ±10000 = одна сторона тянет всё
QUALIFY_TAPS = 5         # минимум тапов для кредита за участие
PARTICIPATION_CREDIT = 200   # крустиков КАЖДОМУ квалифицированному, независимо от исхода

MAX_SIDE_NAME = 24


def _rules() -> dict:
    """Правила раунда одним объектом — фронт печатает, не вычисляет."""
    return {
        "join_sec": JOIN_SEC,
        "pull_sec": PULL_SEC,
        "tap_base": TAP_BASE,
        "tap_decay": TAP_DECAY,
        "tap_min": TAP_MIN,
        "rope_limit": ROPE_LIMIT,
        "scale": SCALE,
        "qualify_taps": QUALIFY_TAPS,
        "participation_credit": PARTICIPATION_CREDIT,
        "outcome_reward": 0,
        "formula_ru": (
            f"n-й тап стоит max({TAP_MIN}, {TAP_BASE} − (n−1)×{TAP_DECAY}) очков. "
            f"Позиция каната = насколько вклад одной команды больше другой: "
            f"(A−B)÷(A+B), где вклад команды нормирован на её размер "
            f"(×{SCALE} ÷ размер). Размер команды фиксируется в момент закрытия "
            "приёма и дальше не меняется. Раунд идёт до конца таймера — "
            "досрочной победы нет."
        ),
        "reward_ru": (
            f"Каждый, кто сделал хотя бы {QUALIFY_TAPS} тапов, получает "
            f"{PARTICIPATION_CREDIT}💎 — одинаково для победившей и проигравшей "
            "стороны и при ничьей. За победу команды крустики НЕ начисляются: "
            "победа даёт только статус."
        ),
    }


def _tap_value(tap_index: int) -> int:
    """Цена тапа по счёту (1-based). Целые числа, никакой случайности."""
    return max(TAP_MIN, TAP_BASE - (tap_index - 1) * TAP_DECAY)


def _batch_value(already: int, taps: int) -> int:
    """Сколько очков дадут `taps` тапов, если до них уже было `already`."""
    return sum(_tap_value(already + i + 1) for i in range(taps))


def _rope_pos(eff_a: int, eff_b: int, team_a: int, team_b: int) -> int:
    """Позиция каната: ОТНОСИТЕЛЬНОЕ преимущество, ±ROPE_LIMIT.

    Первая редакция считала просто разницу нормированных вкладов — и канат
    улетал за отметку от первой же пачки тапов, потому что нормированный вклад
    не ограничен ничем. Позиция обязана быть отношением, а не разностью: она
    показывает, НАСКОЛЬКО одна сторона сильнее другой, а не сколько всего
    натянули. Иначе раунд заканчивался на первом же участнике.

    Целочисленно и симметрично: `(a−b) × LIMIT ÷ (a+b)`. Пусто с обеих сторон —
    канат посередине.
    """
    norm_a = (eff_a * SCALE) // max(1, team_a)
    norm_b = (eff_b * SCALE) // max(1, team_b)
    total = norm_a + norm_b
    if total <= 0:
        return 0
    pos = ((norm_a - norm_b) * ROPE_LIMIT) // total
    return max(-ROPE_LIMIT, min(ROPE_LIMIT, pos))


async def _current_round(conn, channel_id: int) -> Optional[dict]:
    cur = await conn.execute(
        "SELECT id, status, side_a, side_b, join_until, pull_until, "
        "       team_a_size, team_b_size, eff_a, eff_b, pos, result "
        "FROM tug_rounds WHERE channel_id=? AND status != 'finished' "
        "ORDER BY id DESC LIMIT 1",
        (channel_id,))
    row = await cur.fetchone()
    if not row:
        return None
    keys = ("id", "status", "side_a", "side_b", "join_until", "pull_until",
            "team_a_size", "team_b_size", "eff_a", "eff_b", "pos", "result")
    return dict(zip(keys, row))


async def _advance(conn, channel_id: int, rnd: dict) -> dict:
    """Ленивые переходы фаз. Возвращает раунд в актуальном состоянии.

    Здесь же замораживаются размеры команд — ровно один раз, на закрытии
    приёма. Поздние участники делитель не меняют: иначе ценность уже сделанных
    чужих тапов задним числом поехала бы, а это непрозрачная переоценка.
    """
    now = time.time()

    if rnd["status"] == "join" and now >= rnd["join_until"]:
        cur = await conn.execute(
            "SELECT side, COUNT(*) FROM tug_participants "
            "WHERE channel_id=? AND round_id=? GROUP BY side",
            (channel_id, rnd["id"]))
        sizes = {side: n for side, n in await cur.fetchall()}
        team_a = int(sizes.get("a", 0))
        team_b = int(sizes.get("b", 0))
        await conn.execute(
            "UPDATE tug_rounds SET status='pull', team_a_size=?, team_b_size=? "
            "WHERE channel_id=? AND id=?",
            (team_a, team_b, channel_id, rnd["id"]))
        rnd.update(status="pull", team_a_size=team_a, team_b_size=team_b)

    if rnd["status"] == "pull":
        pos = _rope_pos(rnd["eff_a"], rnd["eff_b"],
                        rnd["team_a_size"], rnd["team_b_size"])
        # Досрочного конца нет намеренно: раунд всегда идёт до таймера.
        # Ранняя победа означала бы, что исход решает первый успевший, а
        # опоздавшие тянут вхолостую — и каждое такое правило надо было бы
        # отдельно объяснять в опубликованных правилах раунда.
        if now >= rnd["pull_until"]:
            result = "a" if pos > 0 else ("b" if pos < 0 else "draw")
            await conn.execute(
                "UPDATE tug_rounds SET status='finished', result=?, pos=?, "
                "finished_at=CURRENT_TIMESTAMP WHERE channel_id=? AND id=?",
                (result, pos, channel_id, rnd["id"]))
            rnd.update(status="finished", result=result, pos=pos)
            await _credit_participants(conn, channel_id, rnd["id"])
    return rnd


async def _credit_participants(conn, channel_id: int, round_id: int) -> int:
    """Фиксированный кредит КАЖДОМУ квалифицированному участнику.

    Не зависит от того, кто победил — в этом весь смысл (блокер №1 ревью).
    `credited` защищает от повторной выдачи: статус читают многие, а начислить
    обязаны один раз. Начисление идёт в транзакции вызывающего через
    `add_points_tx` — по правилу «эффект и деньги в одной транзакции».
    """
    cur = await conn.execute(
        "SELECT username FROM tug_participants "
        "WHERE channel_id=? AND round_id=? AND credited=0 AND taps >= ?",
        (channel_id, round_id, QUALIFY_TAPS))
    winners = [r[0] for r in await cur.fetchall()]
    if not winners:
        return 0
    db = get_db()
    for username in winners:
        await db.add_points_tx(conn, username, PARTICIPATION_CREDIT, channel_id)
    await conn.execute(
        "UPDATE tug_participants SET credited=1 "
        "WHERE channel_id=? AND round_id=? AND credited=0 AND taps >= ?",
        (channel_id, round_id, QUALIFY_TAPS))
    log.info("[TUG] ch=%s round=%s кредит за участие %s💎 × %d человек",
             channel_id, round_id, PARTICIPATION_CREDIT, len(winners))
    return len(winners)


async def _me(conn, channel_id: int, round_id: int, username: str) -> Optional[dict]:
    cur = await conn.execute(
        "SELECT side, taps, effective, credited FROM tug_participants "
        "WHERE channel_id=? AND round_id=? AND username=?",
        (channel_id, round_id, username))
    row = await cur.fetchone()
    if not row:
        return None
    return {"side": row[0], "taps": row[1], "effective": row[2],
            "credited": bool(row[3])}


def _public(rnd: dict, me: Optional[dict]) -> dict:
    now = time.time()
    return {
        "round_id":   rnd["id"],
        "status":     rnd["status"],
        "side_a":     rnd["side_a"],
        "side_b":     rnd["side_b"],
        "pos":        rnd["pos"] if rnd["status"] == "finished" else _rope_pos(
            rnd["eff_a"], rnd["eff_b"], rnd["team_a_size"], rnd["team_b_size"]),
        "team_a":     rnd["team_a_size"],
        "team_b":     rnd["team_b_size"],
        "result":     rnd["result"],
        "seconds_left": max(0, int((rnd["join_until"] if rnd["status"] == "join"
                                    else rnd["pull_until"]) - now)),
        "me":         me,
    }


async def status_for(username: str, channel_id: int) -> dict:
    """Состояние раунда + ПОЛНЫЕ правила. Правила отдаём всегда, даже когда
    раунда нет: зритель обязан прочитать их ДО того, как войдёт (блокер №3).

    Отделено от HTTP-обёртки намеренно: тесты бьют сюда, как в кассу
    Bannerlord. Гейт, который нельзя прогнать тестом, — это гейт, про который мы
    узнаём в эфире.
    """
    db = get_db()
    async with db._connect() as conn:
        rnd = await _current_round(conn, channel_id)
        if rnd:
            rnd = await _advance(conn, channel_id, rnd)
            me = await _me(conn, channel_id, rnd["id"], username)
            await conn.commit()
            return {"success": True, "active": rnd["status"] != "finished",
                    "round": _public(rnd, me), "rules": _rules()}
        cur = await conn.execute(
            "SELECT side_a, side_b, result, pos FROM tug_rounds "
            "WHERE channel_id=? AND status='finished' ORDER BY id DESC LIMIT 1",
            (channel_id,))
        last = await cur.fetchone()
    return {
        "success": True, "active": False, "round": None, "rules": _rules(),
        "last": ({"side_a": last[0], "side_b": last[1],
                  "result": last[2], "pos": last[3]} if last else None),
    }


async def join_side(username: str, channel_id: int, side: str) -> dict:
    """Выбрать сторону. Бесплатно. Сторона фиксируется и не меняется."""
    side = (side or "").strip().lower()
    if side not in ("a", "b"):
        return {"success": False, "message": "Выбери сторону: a или b"}

    db = get_db()
    async with db._connect() as conn:
        rnd = await _current_round(conn, channel_id)
        if not rnd:
            return {"success": False, "message": "Раунд ещё не запущен"}
        rnd = await _advance(conn, channel_id, rnd)
        if rnd["status"] != "join":
            await conn.commit()
            return {"success": False,
                    "message": "Приём в этом раунде уже закрыт — дождись следующего"}
        me = await _me(conn, channel_id, rnd["id"], username)
        if me:
            await conn.commit()
            return {"success": False, "side": me["side"],
                    "message": f"Ты уже за «{rnd['side_a'] if me['side'] == 'a' else rnd['side_b']}» — "
                               "перебегать нельзя"}
        await conn.execute(
            "INSERT INTO tug_participants (channel_id, round_id, username, side) "
            "VALUES (?, ?, ?, ?)",
            (channel_id, rnd["id"], username, side))
        await conn.commit()
    return {"success": True, "side": side,
            "message": f"Ты за «{rnd['side_a'] if side == 'a' else rnd['side_b']}». Тяни!"}


async def pull_rope(username: str, channel_id: int, taps: int) -> dict:
    """Тянуть канат. Бесплатно, крустики не списываются.

    Сервер сам считает цену тапов по опубликованной формуле — клиент присылает
    только их количество, и оно урезается до `TAPS_PER_REQUEST`. Плюс окно между
    запросами: автокликер не должен решать исход, а затухание и так съедает
    выгоду от долбления.
    """
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
        rnd = await _current_round(conn, channel_id)
        if not rnd:
            return {"success": False, "message": "Раунд ещё не запущен"}
        rnd = await _advance(conn, channel_id, rnd)
        if rnd["status"] != "pull":
            await conn.commit()
            msg = ("Идёт приём — тяга начнётся, когда он закончится"
                   if rnd["status"] == "join" else "Раунд закончился")
            return {"success": False, "message": msg}
        me = await _me(conn, channel_id, rnd["id"], username)
        if not me:
            await conn.commit()
            return {"success": False,
                    "message": "Ты не выбрал сторону до закрытия приёма"}
        cur = await conn.execute(
            "SELECT last_pull_at FROM tug_participants "
            "WHERE channel_id=? AND round_id=? AND username=?",
            (channel_id, rnd["id"], username))
        last_at = float((await cur.fetchone())[0] or 0)
        if now - last_at < PULL_COOLDOWN_SEC:
            await conn.commit()
            return {"success": False, "message": "Слишком часто — тяни спокойнее"}

        gained = _batch_value(me["taps"], taps)
        await conn.execute(
            "UPDATE tug_participants SET taps=taps+?, effective=effective+?, "
            "last_pull_at=? WHERE channel_id=? AND round_id=? AND username=?",
            (taps, gained, now, channel_id, rnd["id"], username))
        col = "eff_a" if me["side"] == "a" else "eff_b"
        await conn.execute(
            f"UPDATE tug_rounds SET {col} = {col} + ? WHERE channel_id=? AND id=?",
            (gained, channel_id, rnd["id"]))
        rnd[col] += gained
        rnd = await _advance(conn, channel_id, rnd)
        me = await _me(conn, channel_id, rnd["id"], username)
        await conn.commit()
    return {"success": True, "gained": gained, "round": _public(rnd, me)}


async def start_round(cid: int, side_a: str = "", side_b: str = "") -> dict:
    """Запустить раунд на канале. Вызывается кабинетом стримера."""
    side_a = (side_a or "Синие").strip()[:MAX_SIDE_NAME] or "Синие"
    side_b = (side_b or "Красные").strip()[:MAX_SIDE_NAME] or "Красные"

    now = time.time()
    db = get_db()
    async with db._connect() as conn:
        rnd = await _current_round(conn, cid)
        if rnd:
            rnd = await _advance(conn, cid, rnd)
            if rnd["status"] != "finished":
                await conn.commit()
                return {"status": "already_running", "round_id": rnd["id"]}
        cur = await conn.execute(
            "INSERT INTO tug_rounds (channel_id, status, side_a, side_b, "
            " join_until, pull_until) VALUES (?, 'join', ?, ?, ?, ?) RETURNING id",
            (cid, side_a, side_b, now + JOIN_SEC, now + JOIN_SEC + PULL_SEC))
        row = await cur.fetchone()
        await conn.commit()
    log.info("[TUG] ch=%s раунд запущен: «%s» против «%s»", cid, side_a, side_b)
    return {"status": "ok", "round_id": row[0] if row else 0,
            "side_a": side_a, "side_b": side_b}


# ── HTTP-обёртки. Тонкие намеренно: тут только авторизация и разбор тела. ──

@router.get("/api/tugofwar/status")
async def http_status(request: Request):
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth
    return await status_for(username, channel_id)


@router.post("/api/tugofwar/join")
async def http_join(request: Request):
    auth = require_jwt_user(request)
    if not auth:
        return _AUTH_FAIL
    username, channel_id = auth
    try:
        body = await request.json()
    except Exception:
        body = {}
    return await join_side(username, channel_id, body.get("side") or "")


@router.post("/api/tugofwar/pull")
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


@router.post("/api/streamer/tugofwar/start")
async def http_start(request: Request):
    from routes.streamer import _read_session_cookie
    cid = _read_session_cookie(request)
    if cid is None:
        return {"status": "unauthenticated"}
    try:
        body = await request.json()
    except Exception:
        body = {}
    return await start_round(cid, body.get("side_a") or "", body.get("side_b") or "")
