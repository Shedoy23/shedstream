"""
Migration M13: Pets MVP (Phase 7 of COMPLIANCE_REWORK_PLAN.md).

Первая cross-channel механика в extension'е. БОЛЬШИНСТВО таблиц
multi-tenant scope (channel_id в PK), но pets-related — global per
user. Это explicit exception от multi-tenant invariant, документирован
в ARCHITECTURE.md §3.1.

Compliance (см. COMPLIANCE_AND_ARCHITECTURE.md §7.6):
  - Catalog задан extension'ом, не streamer'ом (§6.2.8 protection)
  - Items deterministic (фикс цена, фикс slot) — НЕ mystery box за Bits
    (§6.2.4 ban)
  - Cosmetics-only, НЕТ utility (бустов накопления / преимуществ)
  - НЕ tradable между юзерами (§5.2 — items за loyalty-points OK,
    но не tradable если мы не делаем marketplace)

Schema:
  pet_catalog        — global catalog items, controlled by dev
                       (item_id PK, slot, price_bits, etc.)
  pets               — pet appearance per user (global)
                       (username PK)
  pet_inventory      — owned cosmetics per user (global)
                       ((username, item_id) PK)
  pet_equipped       — currently worn cosmetics per slot
                       ((username, slot) PK)
  pet_purchases      — audit-trail с channel_id (revenue attribution §7.5)
                       (id PK; channel_id хранится для аудита, не для scope)

Идемпотентно через migrations_applied['M13.pets'].
"""

# Default catalog — 5 cosmetics MVP. Phase 7+ можно расширить до 30+.
# Цены в Bits консервативные (300/500/800), pricing-tier параметр.
PETS_CATALOG_SEED = [
    # (item_id, name, slot, price_bits, rarity, emoji)
    ('hat_cap',         'Кепка',      'head',       300, 'common',   '🧢'),
    ('hat_crown',       'Корона',     'head',       800, 'epic',     '👑'),
    ('acc_glasses',     'Очки',       'accessory',  300, 'common',   '👓'),
    ('acc_scarf',       'Шарф',       'accessory',  500, 'rare',     '🧣'),
    ('bg_violet',       'Фиолетовый фон', 'background', 500, 'rare',  '🟣'),
]

PET_BASE_TYPE = 'egg'  # 🥚 яичко-маскот, символ начала (см. PROJECT_PLAYBOOK §5.4)


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M13.pets"):
        return

    # ── pet_catalog ───────────────────────────────────────────────────────────
    # Catalog controlled by dev. Items immutable после release (only deprecate,
    # не delete — иначе сломаются existing pet_equipped/pet_inventory refs).
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS pet_catalog (
            item_id      TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            slot         TEXT NOT NULL CHECK (slot IN ('head', 'accessory', 'background', 'body')),
            price_bits   INTEGER NOT NULL,
            rarity       TEXT NOT NULL DEFAULT 'common'
                         CHECK (rarity IN ('common', 'rare', 'epic', 'legendary')),
            emoji        TEXT,
            deprecated   INTEGER NOT NULL DEFAULT 0,
            created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_pet_catalog_active
            ON pet_catalog(slot, price_bits)
            WHERE deprecated = 0
    """)

    # Seed catalog items (idempotent через INSERT OR IGNORE)
    for item_id, name, slot, price, rarity, emoji in PETS_CATALOG_SEED:
        await conn.execute(
            "INSERT OR IGNORE INTO pet_catalog "
            "(item_id, name, slot, price_bits, rarity, emoji) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (item_id, name, slot, price, rarity, emoji)
        )

    # ── pets ──────────────────────────────────────────────────────────────────
    # GLOBAL: username PK (без channel_id). Cross-channel persistence —
    # explicit exception от multi-tenant invariant (см. ARCHITECTURE.md §3.1).
    await conn.execute(f"""
        CREATE TABLE IF NOT EXISTS pets (
            username     TEXT PRIMARY KEY,
            pet_type     TEXT NOT NULL DEFAULT '{PET_BASE_TYPE}',
            hatched_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            name         TEXT
        )
    """)

    # ── pet_inventory ─────────────────────────────────────────────────────────
    # Owned cosmetics. GLOBAL: ((username, item_id) PK).
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS pet_inventory (
            username     TEXT NOT NULL,
            item_id      TEXT NOT NULL,
            acquired_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (username, item_id),
            FOREIGN KEY (item_id) REFERENCES pet_catalog(item_id)
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_pet_inventory_by_user
            ON pet_inventory(username, acquired_at DESC)
    """)

    # ── pet_equipped ──────────────────────────────────────────────────────────
    # Currently worn cosmetics per slot. Один slot — один item per user (UNIQUE).
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS pet_equipped (
            username     TEXT NOT NULL,
            slot         TEXT NOT NULL,
            item_id      TEXT NOT NULL,
            equipped_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (username, slot),
            FOREIGN KEY (item_id) REFERENCES pet_catalog(item_id)
        )
    """)

    # ── pet_purchases ─────────────────────────────────────────────────────────
    # Audit-trail. channel_id хранится для revenue attribution (§7.5),
    # НЕ для scope (запись global, не tenant-scoped).
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS pet_purchases (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username        TEXT NOT NULL,
            item_id         TEXT NOT NULL,
            channel_id      INTEGER NOT NULL,
            bits_amount     INTEGER NOT NULL,
            bits_receipt    TEXT,                -- Twitch Bits transaction ID (если real)
            mode            TEXT NOT NULL DEFAULT 'mock'
                            CHECK (mode IN ('mock', 'bits')),
            purchased_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_pet_purchases_by_user
            ON pet_purchases(username, purchased_at DESC)
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_pet_purchases_by_channel
            ON pet_purchases(channel_id, purchased_at DESC)
    """)
    # Idempotency: один receipt не может быть применён дважды
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_pet_purchases_receipt
            ON pet_purchases(bits_receipt)
            WHERE bits_receipt IS NOT NULL
    """)

    # ── channel-level setting: pets-in-overlay opt-out ────────────────────────
    # Стример может выключить отображение pets в своём overlay (§7.4
    # broadcaster-control). Default ON.
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS channel_pet_settings (
            channel_id      INTEGER PRIMARY KEY,
            overlay_enabled INTEGER NOT NULL DEFAULT 1,
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    await conn.commit()
    await _mark_applied(conn, "M13.pets")
    print(f"✅ M13: pets tables created + catalog seeded ({len(PETS_CATALOG_SEED)} items)")


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
