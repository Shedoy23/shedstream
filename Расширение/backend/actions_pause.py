# -*- coding: utf-8 -*-
"""actions_pause.py — аварийная пауза воздействий зрителей на игру.

ОДНА функция читает флаг, ОДНА пишет. Модуль намеренно ни от чего внутри
проекта не зависит (как `routes/_mod_queue.py`): его импортируют и касса, и
выдача заданий моду, и кабинет стримера — цикл импортов не должен возникать ни
при каком порядке загрузки.

БЕЗ КЭША, НАМЕРЕННО. Соблазн закэшировать флаг велик — его читает каждый опрос
мода. Но кэшированная пауза отстаёт от нажатия кнопки, а кнопка нажимается
ровно тогда, когда в эфире что-то идёт не так: значение, которое «почти
актуально», здесь равно неработающему. Чтение одной колонки из SQLite стоит
микросекунды, опрос мода приходит раз в секунды.

ПРОПУСК = НЕ НА ПАУЗЕ. Если канала нет в таблице или колонка почему-то
отсутствует, считаем, что паузы нет. Обратный дефолт означал бы, что сбой
чтения молча выключает всю интеграцию у всех — отказ громче, но хуже.
"""
from __future__ import annotations


async def is_paused(conn, channel_id: int) -> bool:
    """Взведена ли пауза у канала. `conn` — открытое соединение вызывающего."""
    try:
        cur = await conn.execute(
            "SELECT actions_paused FROM channels WHERE channel_id=?", (channel_id,))
        row = await cur.fetchone()
    except Exception:
        return False
    return bool(row and row[0])


async def set_paused(conn, channel_id: int, paused: bool) -> None:
    """Взвести или снять паузу. Коммитит вызывающий."""
    await conn.execute(
        "UPDATE channels SET actions_paused=? WHERE channel_id=?",
        (1 if paused else 0, channel_id))


# Текст отказа зрителю. Держим здесь, а не во фронте: фронт заморожен на CDN,
# и причину отказа, которой он не знает, он обязан просто показать
# (CLAUDE.md, «Тонкий фронт»).
PAUSED_MESSAGE = ("Стример поставил интеграцию на паузу — действия сейчас "
                  "не выполняются. Крустики не списаны.")


async def pending_actions_unless_paused(db, channel_id: int, module_id: str,
                                        since_id: int, limit: int) -> list:
    """Задания для мода — или пустой список, пока взведена пауза.

    Отдельная функция, а не условие внутри роута, по одной причине: роут опроса
    требует токен модуля, и проверить его в тесте дорого. Затвор, который нельзя
    прогнать тестом, — это затвор, про который мы узнаем в эфире.
    """
    async with db._connect() as conn:
        if await is_paused(conn, channel_id):
            return []
    return await db.fetch_pending_actions(
        channel_id=channel_id, module_id=module_id,
        since_id=since_id, limit=limit)
