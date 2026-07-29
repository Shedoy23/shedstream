# -*- coding: utf-8 -*-
"""notices.py — почтовый ящик зрителя (M103, 2026-07-29).

Одно короткое сообщение зрителю о том, что произошло без его участия: чаще
всего — почему платное действие не сработало и крустики вернулись.

ЗАЧЕМ ОТДЕЛЬНЫЙ МОДУЛЬ. Тихий возврат случается в нескольких местах (отказ
мода, истечение заявки по TTL, сторож зависших покупок), а «сказать зрителю» —
одна и та же операция. Раньше её не было нигде.

ДВА РЕЖИМА ЗАПИСИ, и путать их нельзя:

  • `add_notice_tx(conn, …)` — пишет на ЧУЖОМ соединении, внутри уже открытой
    транзакции вызывающего. Именно так надо писать уведомление о возврате
    денег: возврат и объяснение обязаны быть одной транзакцией, иначе падение
    между ними даёт либо деньги без объяснения, либо объяснение без денег.
    (Тот же принцип, что у `add_points_tx` — CLAUDE.md, «Charge + effect в ОДНОЙ
    транзакции».)

  • `add_notice(db, …)` — сам открывает соединение и коммитит. Только для мест,
    где рядом нет денежной операции.

Текст приходит СЮДА уже готовым к показу. Панель не переводит коды в слова:
фронт замерзает на CDN до следующего ревью Twitch, а бэк деплоится за минуты —
значит словарь причин должен жить на бэке (CLAUDE.md, «тонкий фронт»).
"""
import logging

logger = logging.getLogger(__name__)

# Сколько дней храним. Уведомление — вещь одноразовая: не прочитал за две
# недели, значит уже не прочитает, а таблица растёт на каждом отказе.
NOTICE_TTL_DAYS = 14

# Потолок на одну выдачу. Зритель, вернувшийся после долгого отсутствия, не
# должен получить сотню тостов подряд.
MAX_UNSEEN_RETURNED = 10


async def add_notice_tx(conn, channel_id: int, username: str, kind: str,
                        text: str, amount: int = 0) -> None:
    """Записать уведомление на соединении вызывающего (без commit).

    Ошибку здесь глотаем намеренно: уведомление — не деньги. Если таблицы ещё
    нет (миграция не прогонялась) или запись не удалась, возврат крустиков
    обязан состояться всё равно. Молчать при этом нельзя — пишем в лог.
    """
    if not username:
        return
    try:
        await conn.execute(
            "INSERT INTO viewer_notices (channel_id, username, kind, text, amount) "
            "VALUES (?, ?, ?, ?, ?)",
            (channel_id, username.lower(), kind, text, int(amount or 0)))
    except Exception as ex:
        logger.warning("[NOTICE] ch=%s user=%s kind=%s не записано: %s",
                       channel_id, username, kind, ex)


async def add_notice(db, channel_id: int, username: str, kind: str,
                     text: str, amount: int = 0) -> None:
    """То же, но со своим соединением и коммитом."""
    async with db._connect() as conn:
        await add_notice_tx(conn, channel_id, username, kind, text, amount)
        await conn.commit()


async def fetch_unseen(db, channel_id: int, username: str):
    """Непрочитанные уведомления зрителя, старые сначала."""
    async with db._connect() as conn:
        cur = await conn.execute(
            "SELECT id, kind, text, amount, created_at FROM viewer_notices "
            "WHERE channel_id=? AND username=? AND seen_at IS NULL "
            "ORDER BY id ASC LIMIT ?",
            (channel_id, username.lower(), MAX_UNSEEN_RETURNED))
        rows = await cur.fetchall()
    return [
        {"id": r[0], "kind": r[1], "text": r[2], "amount": r[3],
         "created_at": r[4]}
        for r in rows
    ]


async def mark_seen(db, channel_id: int, username: str, ids) -> int:
    """Пометить показанные уведомления. Возвращает, сколько реально закрыли.

    Чужие id в списке безвредны: `channel_id` и `username` в WHERE не дают
    закрыть уведомление другого зрителя.
    """
    ids = [int(i) for i in (ids or []) if str(i).lstrip("-").isdigit()][:MAX_UNSEEN_RETURNED]
    if not ids:
        return 0
    placeholders = ",".join("?" * len(ids))
    async with db._connect() as conn:
        cur = await conn.execute(
            f"UPDATE viewer_notices SET seen_at=CURRENT_TIMESTAMP "
            f"WHERE channel_id=? AND username=? AND seen_at IS NULL "
            f"AND id IN ({placeholders})",
            (channel_id, username.lower(), *ids))
        affected = cur.rowcount
        await conn.commit()
    return affected


async def purge_old(db) -> int:
    """Удалить уведомления старше NOTICE_TTL_DAYS. Возвращает число строк."""
    async with db._connect() as conn:
        try:
            cur = await conn.execute(
                "DELETE FROM viewer_notices "
                "WHERE created_at < datetime('now', ?)  -- tenant-ok: сторож по возрасту, все каналы",
                (f"-{NOTICE_TTL_DAYS} days",))
            affected = cur.rowcount
            await conn.commit()
        except Exception as ex:
            logger.warning("[NOTICE] сторож не отработал: %s", ex)
            return 0
    return affected
