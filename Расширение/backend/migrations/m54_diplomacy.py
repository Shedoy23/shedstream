"""
Migration M54 — Diplomacy (BLT-parity, Lait fork inspired).

Sprint 5.33 DIPLO — viewer-king может покупать политические решения для своего
kingdom'а, любой viewer-king может предлагать peace с врагом, любой viewer
может оплатить ransom captured hero (свой или союзный).

3 таблицы:
  bannerlord_policy_requests — pending policy enactments (king-only)
  bannerlord_peace_offers    — pending peace proposals (king-only)
  bannerlord_ransom_pool     — crowd-funded ransom для captured heroes

Workflow policy:
  1. King viewer покупает hero.enact_policy(policy_id) — backend INSERT row.
  2. Mod в next OnHourly tick читает active requests, вызывает
     ChangeKingdomDecisionAction.Apply(EnactPolicyDecision) → enacted=1.
  3. Mod пушит hero.policy_enacted event → backend marks status='enacted'.

Workflow peace:
  1. King viewer покупает hero.make_peace(target_kingdom_id) — backend INSERT row.
  2. Mod вызывает MakePeaceAction.Apply(myKingdom, targetKingdom, dailyTribute=0).
  3. Mod marks completed.

Workflow ransom:
  1. Hero captured → mod пушит player.captured event → backend captured=1 in
     bannerlord_heroes (existing column).
  2. Любой viewer может pay_ransom — пополняет pool для captured hero.
  3. Когда pool >= ransom_cost → backend enqueues mod action.
  4. Mod вызывает EndCaptivityAction.ApplyByRansom(prisoner, payer).
  5. Backend distributes cost from pool → contributors notified.
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M54.diplomacy"):
        return

    # ── Extend bannerlord_heroes с DIPLO fields ──────────────────────────────
    # Mod пушит эти fields в HeroStateSync. Backend читает для:
    #   is_king / is_clan_leader  — авторизация enact_policy / make_peace
    #   kingdom_id (StringId)     — engine resolve для peace target
    #   captured + captor_party   — ransom pool tracking
    cur = await conn.execute("PRAGMA table_info(bannerlord_heroes)")
    existing_cols = {row[1] for row in await cur.fetchall()}
    NEW_COLS = [
        ("kingdom_id",      "TEXT"),       # TaleWorlds Kingdom.StringId
        ("is_clan_leader",  "INTEGER DEFAULT 0"),
        ("is_king",         "INTEGER DEFAULT 0"),
        ("captured",        "INTEGER DEFAULT 0"),
        ("captor_party",    "TEXT"),        # captor MobileParty.StringId
    ]
    for col_name, col_def in NEW_COLS:
        if col_name not in existing_cols:
            await conn.execute(
                f"ALTER TABLE bannerlord_heroes ADD COLUMN {col_name} {col_def}"
            )
    print("M54: bannerlord_heroes extended с kingdom_id/is_king/captured/...")

    # ── Policy requests ──────────────────────────────────────────────────────
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_policy_requests (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id      INTEGER NOT NULL,
            requester       TEXT    NOT NULL,  -- viewer username (must be king)
            kingdom_id      TEXT    NOT NULL,
            policy_id       TEXT    NOT NULL,  -- TaleWorlds PolicyObject.StringId
            policy_name     TEXT,              -- UI readable
            requested_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            status          TEXT    NOT NULL DEFAULT 'pending'
                                              -- pending/enacted/rejected/failed
        )
    """)
    # UNIQUE — один pending request per (kingdom, policy) — антиспам.
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_policy_pending_unique
        ON bannerlord_policy_requests(channel_id, kingdom_id, policy_id)
        WHERE status = 'pending'
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_policy_requester
        ON bannerlord_policy_requests(channel_id, requester, status)
    """)
    print("M54: bannerlord_policy_requests created")

    # ── Peace offers ─────────────────────────────────────────────────────────
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_peace_offers (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id      INTEGER NOT NULL,
            requester       TEXT    NOT NULL,  -- viewer username (king)
            my_kingdom_id   TEXT    NOT NULL,
            target_kingdom_id TEXT  NOT NULL,
            target_kingdom_name TEXT,
            offered_tribute INTEGER NOT NULL DEFAULT 0,  -- daily gold
            offered_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            status          TEXT    NOT NULL DEFAULT 'pending'
                                          -- pending/accepted/rejected/expired
        )
    """)
    # UNIQUE — один pending peace per (my_kingdom, target_kingdom).
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_peace_pending_unique
        ON bannerlord_peace_offers(channel_id, my_kingdom_id, target_kingdom_id)
        WHERE status = 'pending'
    """)
    print("M54: bannerlord_peace_offers created")

    # ── Ransom pool ──────────────────────────────────────────────────────────
    # Crowd-fund для captured heroes. ransom_cost определяется backend'ом
    # из tier/level героя. Когда pool ≥ cost → enqueue release action.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bannerlord_ransom_pool (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id      INTEGER NOT NULL,
            captured_hero   TEXT    NOT NULL,  -- captured viewer username
            contributor     TEXT    NOT NULL,  -- viewer who paid
            amount          INTEGER NOT NULL,
            paid_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            status          TEXT    NOT NULL DEFAULT 'pooled'
                                          -- pooled/released/refunded
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_ransom_captured
        ON bannerlord_ransom_pool(channel_id, captured_hero, status)
    """)
    print("M54: bannerlord_ransom_pool created")

    await conn.commit()
    await _mark_applied(conn, "M54.diplomacy")


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
