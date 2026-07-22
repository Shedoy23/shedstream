"""
Migration M96: расклеить заявки на законы королевства (багрепорт #23).

СИМПТОМ (зритель): «законы не работают, алмазы забирают».

ЧТО НА САМОМ ДЕЛЕ: законы работают. Лог игры показывает 16 применений из
16 заявок («[diplo-policy] ... ENACTED policy ... for <королевство>»), самое
старое — 17 июня. Сломана отчётность: статус заявки не обновлял НИКТО — во
всей кодовой базе не было ни одного UPDATE bannerlord_policy_requests.

Последствия для зрителя (действие стоит 1500💎 — самое дорогое в расширении):
  1. Заявка вечно показывается как «на голосовании», хотя закон давно принят.
  2. Уникальный индекс пускает лишь ОДНУ pending-заявку на (канал, королевство,
     закон) → повторно этот закон не запросить никогда, ответ «уже на
     голосовании». Отменить принятый закон тоже нельзя (мод — переключатель).

Что делает миграция:
  1. Добавляет колонку action_id — по ней приходящий от мода итог
     (hero.policy_result) находит свою строку.
  2. Помечает висящие pending-заявки как 'enacted'. Это НЕ догадка: применение
     каждой подтверждено логом мода. Заодно снимает блокировку уникального
     индекса — зрители смогут снова управлять законами.

Дальше статус закрывается автоматически: мод шлёт hero.policy_result после
ПРОВЕРКИ факта (kingdom.HasPolicy), а тихий no-op отдаёт провал → авторефанд.
ACK от ActionPoller для этого не годится — он приходит success=true ещё до
реальной работы.

Idempotent: migrations_applied['M96.policy_requests_unstick'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M96.policy_requests_unstick"):
        return

    # 1. Колонка action_id (если её ещё нет).
    cur = await conn.execute("PRAGMA table_info(bannerlord_policy_requests)")
    cols = {row[1] for row in await cur.fetchall()}
    if "action_id" not in cols:
        await conn.execute(
            "ALTER TABLE bannerlord_policy_requests ADD COLUMN action_id TEXT")
        print("M96: bannerlord_policy_requests.action_id добавлена")

    # 2. Расклеить висящие заявки. Все они реально применены (лог мода),
    #    поэтому 'enacted', а не 'failed' — зритель получил, за что заплатил.
    cur = await conn.execute(
        "SELECT COUNT(*) FROM bannerlord_policy_requests WHERE status='pending'")
    stuck = (await cur.fetchone())[0]
    if stuck:
        await conn.execute(
            "UPDATE bannerlord_policy_requests SET status='enacted' "
            "WHERE status='pending'")
        print(f"M96: расклеено зависших заявок: {stuck} → 'enacted' "
              f"(подтверждено логом мода; снимает блокировку уникального индекса)")

    await conn.commit()
    await _mark_applied(conn, "M96.policy_requests_unstick")


async def _ensure_migrations_table(conn) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS migrations_applied (
            name TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.commit()


async def _is_applied(conn, name: str) -> bool:
    cur = await conn.execute(
        "SELECT 1 FROM migrations_applied WHERE name = ?", (name,)
    )
    return await cur.fetchone() is not None


async def _mark_applied(conn, name: str) -> None:
    await conn.execute(
        "INSERT OR IGNORE INTO migrations_applied (name) VALUES (?)", (name,)
    )
    await conn.commit()
