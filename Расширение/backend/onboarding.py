# -*- coding: utf-8 -*-
"""Воронка онбординга: какие события бывают и как их записать.

ROADMAP §R4 требует наблюдать путь незнакомого стримера от скачивания Manager до
первого действия его зрителя. Здесь — словарь этого пути и одна функция записи.

ГРАНИЦА ПРИВАТНОСТИ. Сюда не попадают логины, пути на диске, токены и тексты
ошибок «как есть». `result` — это КОД (`ok`, `denied_write`, `backend_down`), а
не сообщение: сообщение может содержать путь. Установка опознаётся анонимным
`installation_id`, который Manager генерит у себя; `channel_id` появляется
только после входа через Twitch и берётся ИЗ ТОКЕНА, а не из тела запроса —
иначе любой мог бы приписать событие чужому каналу.
"""
from __future__ import annotations

import time
from typing import Optional

# Путь до входа в Twitch. Эти события Manager шлёт без токена — иначе мы никогда
# не узнаем, сколько людей отвалилось ДО входа, а это самая интересная часть
# воронки. Список закрытый: чужое имя события не запишется.
PRE_AUTH_EVENTS = frozenset({
    "manager_started",
    "game_detection_started",
    "game_detected",
    "integration_selected",
})

# Путь после входа — только с токеном сессии Manager.
AUTHED_EVENTS = frozenset({
    "manager_authenticated",
    "install_started",
    "install_completed",
    "configuration_completed",
    "mod_heartbeat_received",
    "test_action_completed",
    "technical_ready",
    "support_incident_created",
})

# События, которые бэкенд выводит сам из того, что уже знает: их не присылают,
# их замечают. Отдельный список, чтобы никто не мог прислать их снаружи и
# нарисовать себе успешную воронку.
DERIVED_EVENTS = frozenset({
    "extension_activated",
    "first_viewer_open",
    "first_viewer_join",
    "first_viewer_action",
    "stream_session_started",
    "stream_session_ended",
})

KNOWN_EVENTS = PRE_AUTH_EVENTS | AUTHED_EVENTS | DERIVED_EVENTS

_MAX_FIELD = 120


def _clip(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:_MAX_FIELD]


async def record(
    conn,
    event: str,
    *,
    installation_id: Optional[str] = None,
    channel_id: Optional[int] = None,
    integration_id: Optional[str] = None,
    integration_version: Optional[str] = None,
    manager_version: Optional[str] = None,
    elapsed_ms: Optional[int] = None,
    result: Optional[str] = None,
    source_step: Optional[str] = None,
    client_event_id: Optional[str] = None,
    now: Optional[float] = None,
) -> bool:
    """Записать одно событие воронки. Возвращает False, если это повтор.

    Пишет на переданном соединении и НЕ коммитит: вызывающий решает, в какой
    транзакции это живёт. Телеметрия не должна ни ломать, ни задерживать то
    действие, ради которого её пишут.
    """
    if event not in KNOWN_EVENTS:
        raise ValueError("unknown onboarding event: %s" % event)
    cur = await conn.execute(
        "INSERT OR IGNORE INTO onboarding_events "
        "(event, installation_id, channel_id, integration_id, integration_version, "
        " manager_version, elapsed_ms, result, source_step, client_event_id, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            event,
            _clip(installation_id),
            int(channel_id) if channel_id is not None else None,
            _clip(integration_id),
            _clip(integration_version),
            _clip(manager_version),
            int(elapsed_ms) if elapsed_ms is not None else None,
            _clip(result),
            _clip(source_step),
            _clip(client_event_id),
            float(time.time() if now is None else now),
        ),
    )
    return bool(cur.rowcount)


async def note_once(conn, event: str, channel_id: int, **fields) -> bool:
    """Отметить событие, которое у канала бывает ПЕРВЫМ РАЗОМ и только раз.

    Для `first_viewer_action` и подобных: второй вызов ничего не пишет. Без
    этого «первое действие зрителя» превратилось бы в счётчик всех действий, а
    в воронке нужен именно момент, когда это случилось впервые.
    """
    cur = await conn.execute(
        "SELECT 1 FROM onboarding_events WHERE event=? AND channel_id=? LIMIT 1",
        (event, int(channel_id)),
    )
    if await cur.fetchone():
        return False
    return await record(conn, event, channel_id=channel_id, **fields)
