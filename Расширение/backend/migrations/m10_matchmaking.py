"""
Migration M10: matchmaking base (Phase 5.0 of COMPLIANCE_REWORK_PLAN.md).

Базовая инфраструктура multi-game matchmaking поверх которой работают
PvP-игры (RPS, TicTacToe, Dice, etc). Phase 5.0 = база, далее Phase 5.1
TicTacToe MVP + Phase 5.2 Dice.

Что делает:
  1. CREATE match_queue — очередь игроков ожидающих противника
  2. CREATE match_rooms — активные комнаты после matchmaking
  3. Rebuild duel_stats: добавить channel_id + game_type в PK
     (multi-tenant + per-game ELO)
  4. Rebuild duel_seasons: добавить channel_id + game_type
     (sезоны per channel per game)
  5. DROP старая pending_duels (Phase 1.F очистила amount; теперь после
     перехода на match_queue old table не используется)

Идемпотентно через migrations_applied['M10.matchmaking'].

Backfill старых данных:
  - duel_stats: existing rows получают channel_id=98319857 (DEFAULT_CHANNEL_ID
    из M1), game_type='rps'
  - duel_seasons: existing rows получают channel_id=98319857, game_type='rps'

Требует SQLite ≥ 3.35 (DROP/RENAME TABLE supported). На проде 3.45.
"""

DEFAULT_CHANNEL_ID = 98319857  # shedoy23, backfill anchor (same as M1)


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M10.matchmaking"):
        return

    # ── 1. match_queue ────────────────────────────────────────────────────────
    # Юзер встаёт в очередь на конкретный game_type. matchmaking_loop ищет
    # пары по близкому ELO (внутри game_type + channel_id).
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS match_queue (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id      INTEGER NOT NULL,
            username        TEXT NOT NULL,
            game_type       TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'queued'
                            CHECK (status IN ('queued', 'matched', 'cancelled', 'expired')),
            elo_at_queue    INTEGER NOT NULL DEFAULT 1100,
            elo_spread      INTEGER NOT NULL DEFAULT 100,
            queued_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            matched_with    INTEGER,  -- match_queue.id оппонента после match
            room_id         TEXT,     -- match_rooms.room_id после match
            matched_at      TIMESTAMP
        )
    """)

    # Индекс для matchmaking_loop: быстрый поиск queued внутри
    # (channel_id, game_type) отсортированный по elo для pair-matching.
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_match_queue_active
            ON match_queue(channel_id, game_type, elo_at_queue)
            WHERE status = 'queued'
    """)

    # Constraint защита: один юзер — одна активная queue-запись per game_type.
    # Реализовано через partial unique index.
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_match_queue_active_user
            ON match_queue(channel_id, username, game_type)
            WHERE status = 'queued'
    """)

    # ── 2. match_rooms ────────────────────────────────────────────────────────
    # Активная комната после matchmaking. Игроки шлют moves в room_state JSON.
    # game-specific state-machine хранится в `state` поле (JSON parsed на
    # frontend / processor). Backend знает только generic lifecycle.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS match_rooms (
            room_id         TEXT PRIMARY KEY,
            channel_id      INTEGER NOT NULL,
            game_type       TEXT NOT NULL,
            player_a        TEXT NOT NULL,
            player_b        TEXT NOT NULL,
            player_a_elo    INTEGER NOT NULL DEFAULT 1100,
            player_b_elo    INTEGER NOT NULL DEFAULT 1100,
            state           TEXT NOT NULL DEFAULT '{}',  -- JSON game-specific
            status          TEXT NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'finished', 'expired', 'aborted')),
            winner          TEXT,     -- username победителя | NULL для draw / unfinished
            outcome         TEXT,     -- 'win_a' | 'win_b' | 'draw' | 'timeout' | NULL
            created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at     TIMESTAMP
        )
    """)

    # Index для poll'а активных rooms per channel/user
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_match_rooms_active
            ON match_rooms(channel_id, status, created_at DESC)
            WHERE status = 'active'
    """)

    # Index для поиска rooms по username (player_a OR player_b)
    # SQLite не поддерживает OR в partial index, используем два индекса.
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_match_rooms_player_a
            ON match_rooms(channel_id, player_a, status)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_match_rooms_player_b
            ON match_rooms(channel_id, player_b, status)
    """)

    # ── 3. Rebuild duel_stats: channel_id + game_type в PK ────────────────────
    # SQLite не позволяет ALTER PRIMARY KEY — нужен полный rebuild через
    # rename + recreate + insert.
    try:
        cur = await conn.execute("PRAGMA table_info(duel_stats)")
        cols = {row[1] for row in await cur.fetchall()}
        needs_rebuild = 'channel_id' not in cols or 'game_type' not in cols
    except Exception:
        needs_rebuild = True

    if needs_rebuild:
        # Создаём temporary new table с правильным PK
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS duel_stats_new (
                channel_id    INTEGER NOT NULL,
                username      TEXT NOT NULL,
                game_type     TEXT NOT NULL DEFAULT 'rps',
                elo           INTEGER NOT NULL DEFAULT 1100,
                win_streak    INTEGER NOT NULL DEFAULT 0,
                season_id     INTEGER NOT NULL DEFAULT 1,
                updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (channel_id, username, game_type)
            )
        """)
        # Backfill: все existing rows → channel_id=DEFAULT, game_type='rps'
        try:
            await conn.execute(f"""
                INSERT OR IGNORE INTO duel_stats_new
                    (channel_id, username, game_type, elo, win_streak, season_id)
                SELECT {DEFAULT_CHANNEL_ID}, username, 'rps', elo, win_streak, season_id
                FROM duel_stats
            """)
            print(f"✅ M10: duel_stats backfilled into new schema (channel={DEFAULT_CHANNEL_ID}, game='rps')")
        except Exception as e:
            print(f"⚠️  M10: duel_stats backfill failed (likely empty old table): {e}")

        # Swap tables
        await conn.execute("DROP TABLE IF EXISTS duel_stats")
        await conn.execute("ALTER TABLE duel_stats_new RENAME TO duel_stats")

        # Index для leaderboard (топ по ELO per channel/game/season)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_duel_stats_leaderboard
                ON duel_stats(channel_id, game_type, season_id, elo DESC)
        """)
        print("✅ M10: duel_stats rebuilt with (channel_id, username, game_type) PK")

    # ── 4. Rebuild duel_seasons: channel_id + game_type ───────────────────────
    try:
        cur = await conn.execute("PRAGMA table_info(duel_seasons)")
        cols = {row[1] for row in await cur.fetchall()}
        needs_rebuild = 'channel_id' not in cols or 'game_type' not in cols
    except Exception:
        needs_rebuild = True

    if needs_rebuild:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS duel_seasons_new (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id    INTEGER NOT NULL,
                game_type     TEXT NOT NULL DEFAULT 'rps',
                started_at    TEXT NOT NULL,
                ends_at       TEXT NOT NULL,
                finished      INTEGER NOT NULL DEFAULT 0
            )
        """)
        try:
            await conn.execute(f"""
                INSERT OR IGNORE INTO duel_seasons_new
                    (id, channel_id, game_type, started_at, ends_at, finished)
                SELECT id, {DEFAULT_CHANNEL_ID}, 'rps', started_at, ends_at, finished
                FROM duel_seasons
            """)
            print(f"✅ M10: duel_seasons backfilled (channel={DEFAULT_CHANNEL_ID}, game='rps')")
        except Exception as e:
            print(f"⚠️  M10: duel_seasons backfill failed (likely empty): {e}")

        await conn.execute("DROP TABLE IF EXISTS duel_seasons")
        await conn.execute("ALTER TABLE duel_seasons_new RENAME TO duel_seasons")

        # Unique active season per (channel, game)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_duel_seasons_active
                ON duel_seasons(channel_id, game_type, finished)
        """)
        print("✅ M10: duel_seasons rebuilt with channel_id + game_type")

    # ── 5. DROP старая pending_duels (после Phase 1.F + M8 уже пустая) ────────
    try:
        await conn.execute("DROP TABLE IF EXISTS pending_duels")
        print("✅ M10: pending_duels (legacy) dropped — replaced by match_queue")
    except Exception as e:
        print(f"⚠️  M10: pending_duels drop failed: {e}")

    await conn.commit()
    await _mark_applied(conn, "M10.matchmaking")
    print("✅ M10: matchmaking base ready")


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
