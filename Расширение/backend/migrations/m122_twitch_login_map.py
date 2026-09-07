"""
Migration M122: связка Twitch-идентификатор → логин переживает перезапуск.

Логин зрителя резолвится через `dependencies.resolve_jwt_login`, который для
opaque-токена смотрит в `_twitch_login_cache` — словарь В ПАМЯТИ ПРОЦЕССА.
Заполняется он один раз, при загрузке панели (`/api/user/resolve-twitch-token`
→ Helix). В базу не писался никогда.

Отсюда дефект, найденный 07.09: перезапуск бэкенда очищает словарь, и у всех,
у кого панель УЖЕ открыта, `require_jwt_user` перестаёт опознавать зрителя.
Эндпоинты отвечают HTTP 200 с {"status": "unauthorized"} без поля points, а
панель рисует нули — баланс, доход, квесты, кейсы. У владельца в этот момент в
базе лежало 11 058 327💎. Каждый деплой делал это со всеми открытыми панелями,
пока зритель сам не перезагрузит страницу.

Таблица не арендаторская: связка «этот Twitch-аккаунт называется так» одна на
всю платформу и от канала не зависит — как и сам Twitch-логин. Ключом идёт и
числовой user_id, и opaque_user_id, потому что resolve_jwt_login ищет по обоим.

Аддитивно. Idempotent: migrations_applied['M122.twitch_login_map'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M122.twitch_login_map"):
        return

    # tenant-ok: глобальная связка Twitch ID → логин, к каналу не относится
    # (логин у аккаунта один на весь Twitch). Скоупить её channel_id значило бы
    # хранить одно и то же имя по копии на канал.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS twitch_login_map (
            key        TEXT NOT NULL PRIMARY KEY,
            login      TEXT NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    await conn.commit()
    await _mark_applied(conn, "M122.twitch_login_map")
    print("M122: twitch_login_map created")


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
