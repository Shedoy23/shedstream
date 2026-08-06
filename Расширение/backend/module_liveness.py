# -*- coding: utf-8 -*-
"""module_liveness.py — какая игра сейчас реально на связи.

ЗАЧЕМ (решение владельца 2026-08-06, фаза 1).

Раньше «активная игра» была РУЧНОЙ настройкой канала: стример один раз выбрал
Bannerlord — и расширение предлагало действия Bannerlord всегда, даже когда он
играет во что-то другое. 05.08 это стоило пяти зрителям ежедневного бонуса:
они нажали «забрать», отметка «сегодня забрал» записалась, а награда не
выдалась, потому что мода не было. Возврат сработал и вернул ноль — верно,
дейлик бесплатный; пропала не валюта, а право забрать бонус в тот день.

Теперь активность определяется по СИГНАЛУ мода. Мод постоянно опрашивает
сервер за заданиями, поэтому запущенная, но простаивающая игра считается живой.

Три вещи, которые здесь решены намеренно:

1. **Отметка в БАЗЕ, а не в памяти.** Словарь в процессе обнулялся бы каждым
   деплоем, и посреди стрима расширение у всех зрителей на полминуты объявляло
   бы игру выключенной. В памяти держим кэш — чтобы не ходить в базу на каждый
   запрос зрителя, — но истина в таблице `module_last_seen` (миграция M109).

2. **Сердцебиение для ВСЕХ модулей.** До этого отметку обновлял только
   Bannerlord (в коде так и было записано: «обобщить позже»). Для остальных
   она бы не обновлялась, и тихий мод считался бы мёртвым посреди рабочей игры.

3. **Живы двое — активен тот, чей сигнал свежее.** Bannerlord может висеть в
   фоне, пока идёт колония; выбираем по времени, а не по алфавиту.
"""
from __future__ import annotations

import time

# Порог «на связи». Тот же, что на дашборде стримера, чтобы два экрана не
# говорили разное. Мод опрашивает сервер чаще (long-poll 25 сек).
ONLINE_WINDOW_SEC = 60

# Кэш поверх таблицы: {(channel_id, module_id): ts}. Не источник истины —
# ускорение. Пустой кэш после рестарта восполняется чтением из БД.
_cache: dict = {}

# Запись в БД не чаще раза в N секунд на канал+модуль: мод стучится каждые
# ~25 сек, но при нескольких каналах это всё равно лишние записи на диск.
_WRITE_THROTTLE_SEC = 20
_last_write: dict = {}


async def touch(db, channel_id: int, module_id: str) -> None:
    """Отметить, что мод этого модуля только что был на связи."""
    if not module_id:
        return
    now = time.time()
    key = (int(channel_id), module_id)
    _cache[key] = now

    if now - _last_write.get(key, 0.0) < _WRITE_THROTTLE_SEC:
        return
    _last_write[key] = now
    try:
        async with db._connect() as conn:
            await conn.execute(
                "INSERT INTO module_last_seen (channel_id, module_id, last_seen_ts) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(channel_id, module_id) DO UPDATE SET last_seen_ts=excluded.last_seen_ts",
                (int(channel_id), module_id, now))
            await conn.commit()
    except Exception:
        # Отметка — вспомогательный сигнал. Если диск занят, кэш в памяти всё
        # ещё верен, и терять из-за этого запрос зрителя нельзя.
        pass


async def last_seen(db, channel_id: int, module_id: str) -> float:
    """Unix-время последнего сигнала модуля. 0 — сигнала не было никогда."""
    key = (int(channel_id), module_id)
    cached = _cache.get(key)
    if cached:
        return cached
    try:
        async with db._connect() as conn:
            cur = await conn.execute(
                "SELECT last_seen_ts FROM module_last_seen "
                "WHERE channel_id=? AND module_id=?",
                (int(channel_id), module_id))
            row = await cur.fetchone()
    except Exception:
        return 0.0
    if not row:
        return 0.0
    _cache[key] = float(row[0])
    return float(row[0])


async def is_on_air(db, channel_id: int, module_id: str) -> bool:
    ts = await last_seen(db, channel_id, module_id)
    return bool(ts) and (time.time() - ts) < ONLINE_WINDOW_SEC


async def live_module(db, channel_id: int):
    """Какая игра на связи прямо сейчас. None — ни одна.

    Живы несколько — берём ту, чей сигнал свежее.
    """
    now = time.time()
    best, best_ts = None, 0.0
    try:
        async with db._connect() as conn:
            cur = await conn.execute(
                "SELECT module_id, last_seen_ts FROM module_last_seen WHERE channel_id=?",
                (int(channel_id),))
            rows = await cur.fetchall()
    except Exception:
        rows = []

    for module_id, ts in rows:
        _cache[(int(channel_id), module_id)] = float(ts)

    # Кэш может быть свежее таблицы (запись придушена троттлингом), поэтому
    # сверяем оба источника, а не только прочитанное.
    for (ch, module_id), ts in list(_cache.items()):
        if ch != int(channel_id):
            continue
        if now - ts < ONLINE_WINDOW_SEC and ts > best_ts:
            best, best_ts = module_id, ts
    return best
