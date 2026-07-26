"""
feature_usage.py — лёгкий счётчик использования фич (ROADMAP 2.3).

record_feature_use(channel_id, feature_key) делает UPSERT в feature_usage
(per-channel, per-feature, per-day). Best-effort: любые ошибки глотаются —
метрика не критична, действие зрителя важнее. Таблица — миграция m72.
"""
from datetime import datetime, timezone


async def record_feature_use(channel_id: int, feature_key: str, n: int = 1) -> None:
    """+n к счётчику (channel_id, feature_key, сегодня UTC). Никогда не бросает."""
    if not channel_id or not feature_key:
        return
    try:
        from dependencies import get_db
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        db = get_db()

        # M100 — что было в эфире. Без этого метрика смешивает «не захотели»
        # и «не могли»: стример не играет в две игры сразу, поэтому у неактивного
        # модуля ноль гарантирован устройством и ничего не означает. Ровно на
        # этом 2026-07-26 был сделан неверный вывод «RimWorld не нужен».
        active_module = None
        try:
            ch = await db.get_channel(channel_id)
            if ch:
                active_module = ch.get("active_module")
        except Exception:
            pass

        async with db._connect() as conn:
            await conn.execute(
                """
                INSERT INTO feature_usage (channel_id, feature_key, day, count,
                                           active_module)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(channel_id, feature_key, day)
                DO UPDATE SET count = count + excluded.count,
                              active_module = COALESCE(excluded.active_module,
                                                       feature_usage.active_module)
                """,
                (channel_id, feature_key, day, n, active_module))
            await conn.commit()
    except Exception:
        pass  # метрика best-effort — не ломаем действие
