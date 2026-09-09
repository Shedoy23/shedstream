"""
Migration M123: `bannerlord_heroes.state_ts` — защита порядка снимков состояния.

ЗАЧЕМ. `player.state_update` перезаписывал строку героя ВСЛЕПУЮ: кто пришёл
последним, тот и записал. Порядок прихода не связан с порядком отправки, и
клиент гарантировать его не может в принципе:

  * событийные пуши (`HeroStateSync.Push`) идут параллельно периодическому
    зеркалу и обгоняют его;
  * по HTTP-таймауту (35 с) мод НЕ знает, применил сервер запрос или нет:
    «неудачная» отправка может завершиться на сервере ПОЗЖЕ следующей.

Отсюда наблюдаемое следствие: в базе остаётся устаревший снимок, а мод считает
актуальный доставленным и больше его не шлёт — зеркало замирает до следующего
изменения героя.

Клиентская сериализация уменьшает вероятность, но не закрывает случай таймаута.
Порядок обязан защищать тот, кто применяет — то есть бэкенд. `state_ts` хранит
`ts` конверта (epoch ms на стороне мода) последнего ПРИМЕНЁННОГО снимка;
обработчик отбрасывает конверт с меньшим `ts`.

Почему `ts` конверта, а не новое поле: он уже есть в протоколе
(`ModuleEnvelope.ts`, ставится в `BackendClient` при отправке), менять формат
события и версию мода не нужно.

NULL = порядок ещё не известен (старый мод или первый снимок) — такой конверт
применяется, как раньше.

Аддитивно. Idempotent: migrations_applied['M123.hero_state_ts'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M123.hero_state_ts"):
        return

    if not await _has_column(conn, "bannerlord_heroes", "state_ts"):
        # tenant-ok: колонка в уже скоупленной по channel_id таблице героев.
        await conn.execute(
            "ALTER TABLE bannerlord_heroes ADD COLUMN state_ts INTEGER")

    await conn.commit()
    await _mark_applied(conn, "M123.hero_state_ts")
    print("M123: bannerlord_heroes.state_ts added")


async def _has_column(conn, table: str, column: str) -> bool:
    cur = await conn.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    return any(r[1] == column for r in rows)


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
