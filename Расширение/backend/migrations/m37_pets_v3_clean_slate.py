"""
Migration M37: pets v3 — clean slate for pixel-art overhaul (Sprint 5.28, 2026-05-24).

Pets v2 (sprint 5.21-5.22) → v3 visual rewrite:
  • Frontend: emoji-blob creature → PixelLab pixel-art chibi character
  • DB: emoji-items catalog (M30 +15) → empty, ждёт PixelLab batch (separate migration)
  • Architecture: layer-overlay items via svg_path или png_path

Юзеры на проде в курсе test-mode (PETS_BITS_REQUIRED=False, mock bits) — никакие
реальные деньги не тратились, refund/compensation не нужен. Чистим всё чтобы
не таскать legacy state в v3.

Что делает миграция:
  1. Wipe pet_purchases — audit trail (mock-mode записи, не привязаны к деньгам)
  2. Wipe pet_equipped — никто не носит deleted items
  3. Wipe pet_inventory — никаких owned items (FK на удаляемый catalog)
  4. Wipe pets — reset hatched state, юзеры начинают с egg (PET_BASE_TYPE='egg')
  5. Rebuild pet_catalog:
     • CHECK rarity дополнен 'mythic' (было common/rare/epic/legendary)
     • Новая колонка png_path TEXT NULLABLE для PixelLab assets
     • Empty after rebuild — items будут добавлены отдельной миграцией M38
       когда PixelLab batch готов

SQLite quirk: CHECK constraint нельзя ALTER, нужен table rebuild (как в M29).

Idempotent через migrations_applied['M37.pets_v3_clean_slate'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M37.pets_v3_clean_slate"):
        return

    # ── 1. Wipe transient pets data ───────────────────────────────────────────
    # FK chain: pet_inventory/equipped/purchases → pet_catalog. Без catalog
    # эти записи становятся orphan'ами. Чистим в правильном порядке:
    # сначала children (purchases, equipped, inventory), потом parents (pets, catalog).
    await conn.execute("DELETE FROM pet_purchases")
    await conn.execute("DELETE FROM pet_equipped")
    await conn.execute("DELETE FROM pet_inventory")
    await conn.execute("DELETE FROM pets")

    # ── 2. Rebuild pet_catalog ────────────────────────────────────────────────
    # SQLite не позволяет ALTER CHECK constraint → rebuild через CREATE NEW +
    # DROP OLD + RENAME. Catalog после rebuild — пустой (items добавятся M38).
    await conn.execute("DROP TABLE IF EXISTS pet_catalog_new")
    await conn.execute("""
        CREATE TABLE pet_catalog_new (
            item_id      TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            slot         TEXT NOT NULL CHECK (slot IN (
                'head', 'face', 'accessory', 'body', 'background', 'aura'
            )),
            price_bits   INTEGER NOT NULL,
            rarity       TEXT NOT NULL DEFAULT 'common'
                         CHECK (rarity IN (
                             'common', 'rare', 'epic', 'legendary', 'mythic'
                         )),
            emoji        TEXT,           -- legacy field, kept for backward-compat schema
            svg_path     TEXT,           -- inline SVG для Claude Design items (M29 column)
            png_path     TEXT,           -- NEW v3: path к PNG asset (PixelLab generations)
            deprecated   INTEGER NOT NULL DEFAULT 0,
            created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # NO data copy — мы делаем clean slate. Старые items (hat_top, face_sunglasses, etc.)
    # навсегда выкинуты.

    await conn.execute("DROP TABLE pet_catalog")
    await conn.execute("ALTER TABLE pet_catalog_new RENAME TO pet_catalog")

    # Recreate index для active (non-deprecated) items по slot+price
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_pet_catalog_active
            ON pet_catalog(slot, price_bits)
            WHERE deprecated = 0
    """)

    await conn.commit()
    await _mark_applied(conn, "M37.pets_v3_clean_slate")
    print(
        "✅ M37: pets clean-slate "
        "(wipe pets/equipped/inventory/purchases + catalog rebuild "
        "with mythic rarity + png_path column)"
    )


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
