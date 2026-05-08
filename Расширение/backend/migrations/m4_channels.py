"""
M4.0: Channels registry — таблица зарегистрированных стримеров платформы.

Цель: явный реестр каналов которые могут пользоваться расширением. Заменяет
неявный single-tenant `TWITCH_BROADCASTER_ID`-fallback на M4+.

После этой миграции (но прим. в M4.1):
- Любой запрос с JWT.channel_id, для которого нет записи в `channels`,
  получает 403 + `{"status": "channel_not_registered"}`.
- DEFAULT_CHANNEL_ID в resolve_channel_id() становится «backstop» только для
  background tasks где известно что канал в реестре (M4.2).

Backfill: существующий single-tenant стример (TWITCH_BROADCASTER_ID из .env)
автоматически добавляется со статусом `tier='vip'` и `active_module='rimworld'`,
чтобы прод-сервис не сломался после деплоя.

Идемпотентно через `migrations_applied`.

Связано с docs/MULTITENANT_PLAN.md §I, PLATFORM_VISION.md §дорожная карта M4.
"""
import os


CHANNELS_SCHEMA = """
    channel_id INTEGER PRIMARY KEY,
    login TEXT NOT NULL,
    display_name TEXT,
    tier TEXT NOT NULL DEFAULT 'free',
    active_module TEXT DEFAULT NULL,
    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- Twitch OAuth (заполняется в M4.3 OAuth flow)
    oauth_access_token TEXT,
    oauth_refresh_token TEXT,
    oauth_expires_at TIMESTAMP,
    -- EventSub (заполняется в M4.5 auto-register)
    eventsub_subscription_id TEXT
"""


async def apply(conn) -> None:
    """Создать channels таблицу + backfill существующего single-tenant стримера."""
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M4.channels.create"):
        return

    await conn.execute(f"CREATE TABLE IF NOT EXISTS channels ({CHANNELS_SCHEMA})")
    await conn.commit()
    print("✅ M4: channels table created")

    # Backfill — существующий стример из .env
    chan_id_str = (os.getenv("TWITCH_BROADCASTER_ID") or "").strip()
    chan_login  = (os.getenv("TWITCH_CHANNEL_NAME") or "").strip().lower()

    if chan_id_str.isdigit() and chan_login:
        chan_id = int(chan_id_str)
        # ON CONFLICT — повторный запуск миграции на той же базе не дублирует
        await conn.execute(
            """
            INSERT INTO channels (channel_id, login, display_name, tier, active_module)
            VALUES (?, ?, ?, 'vip', 'rimworld')
            ON CONFLICT(channel_id) DO NOTHING
            """,
            (chan_id, chan_login, chan_login),
        )
        await conn.commit()
        print(f"✅ M4: backfilled channel {chan_id} ({chan_login}) tier=vip module=rimworld")
    else:
        print(
            "⚠️  M4: TWITCH_BROADCASTER_ID или TWITCH_CHANNEL_NAME не заданы — "
            "backfill пропущен. Регистрация через /streamer OAuth (M4.3)."
        )

    await _mark_applied(conn, "M4.channels.create")


async def _ensure_migrations_table(conn) -> None:
    """`migrations_applied` создаётся в M1, но для defensive idempotency дублируем."""
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
