"""
bug_reports.py — багрепорты от зрителей через чат-команду !баг (m73).

Зритель: `!баг <текст>` в чате → record_bug_report() сохраняет (channel_id-scoped).
Анти-спам: in-memory кулдаун per (channel_id, username). Стример читает через
list_bug_reports() в дашборде; set_bug_status() помечает resolved.
"""
import time

BUG_COOLDOWN_SEC = 60      # один багрепорт в минуту на зрителя
BUG_MAX_LEN = 500          # обрезаем длинные сообщения

# in-memory: (channel_id, username_lower) -> monotonic ts последнего репорта
_last_report_at = {}


def cooldown_left(channel_id: int, username: str) -> int:
    """Сколько секунд осталось до следующего разрешённого репорта (0 = можно)."""
    key = (channel_id, (username or "").lower())
    last = _last_report_at.get(key)
    if last is None:
        return 0
    left = BUG_COOLDOWN_SEC - (time.monotonic() - last)
    return max(0, int(left + 0.999))  # округляем вверх, чтобы не показывать 0 пока на КД


def mark_reported(channel_id: int, username: str) -> None:
    _last_report_at[(channel_id, (username or "").lower())] = time.monotonic()


async def record_bug_report(channel_id: int, username: str, message: str) -> int:
    """Сохраняет багрепорт, возвращает id. Сообщение обрезается до BUG_MAX_LEN."""
    msg = (message or "").strip()[:BUG_MAX_LEN]
    from dependencies import get_db
    db = get_db()
    async with db._connect() as conn:
        cur = await conn.execute(
            "INSERT INTO bug_reports (channel_id, username, message) VALUES (?, ?, ?)",
            (channel_id, username, msg))
        await conn.commit()
        return cur.lastrowid


_COLS = ["id", "username", "message", "status", "created_at"]


async def list_bug_reports(channel_id: int, limit: int = 50, status: str = None) -> list:
    """Список багрепортов канала (новые сверху). status='open'|'resolved'|None(все)."""
    from dependencies import get_db
    db = get_db()
    async with db._connect() as conn:
        q = ("SELECT id, username, message, status, created_at FROM bug_reports "
             "WHERE channel_id = ?")
        params = [channel_id]
        if status in ("open", "resolved"):
            q += " AND status = ?"
            params.append(status)
        q += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(max(1, min(int(limit or 50), 200)))
        cur = await conn.execute(q, params)
        rows = await cur.fetchall()
        return [dict(zip(_COLS, r)) for r in rows]


async def set_bug_status(channel_id: int, report_id: int, status: str) -> bool:
    """Помечает багрепорт open/resolved (scoped по channel_id). True если строка затронута."""
    if status not in ("open", "resolved"):
        return False
    from dependencies import get_db
    db = get_db()
    async with db._connect() as conn:
        cur = await conn.execute(
            "UPDATE bug_reports SET status = ? WHERE id = ? AND channel_id = ?",
            (status, int(report_id), channel_id))
        await conn.commit()
        return cur.rowcount > 0
