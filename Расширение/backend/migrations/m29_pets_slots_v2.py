"""
Migration M29: Pets schema v2 — Phase 7+ extensions (2026-05-20, Sprint 5.21).

Изменения:
  • pet_catalog.slot CHECK расширен с 4 → 6 slots:
      ('head', 'accessory', 'background', 'body')
      → ('head', 'face', 'accessory', 'body', 'background', 'aura')
    Зачем: рендеринг items на правильных частях creature'а. Очки идут на
    'face' (глаза), шапка — 'head' (макушка), шарф — 'body' (грудь),
    accessory резервируется для side-companion'ов (мячик/шарик/рядом стоит),
    aura — пульсирующее свечение для legendary fluff.

  • pet_catalog.svg_path TEXT (nullable) — опциональный inline SVG path
    для items вместо emoji. Frontend: если svg_path есть — рендерит svg,
    иначе emoji fallback. MVP: existing items остаются emoji-only.

  • Существующий item acc_scarf переезжает 'accessory' → 'body' (шарф —
    это нашейный/нагрудный аксессуар, не лицо). pet_equipped rows
    мигрируются параллельно (slot column там без CHECK constraint, просто
    UPDATE).

SQLite CHECK constraint нельзя изменить ALTER'ом — rebuild pet_catalog
через CREATE NEW → INSERT → DROP OLD → RENAME.

Idempotent через migrations_applied['M29.pets_slots_v2'].
"""


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M29.pets_slots_v2"):
        return

    # ── 1. ADD COLUMN svg_path (idempotent через try/except) ──────────────────
    try:
        await conn.execute("ALTER TABLE pet_catalog ADD COLUMN svg_path TEXT")
    except Exception:
        # Колонка уже существует (M29 retry после частичного выполнения)
        pass

    # ── 2. Rebuild pet_catalog с расширенным CHECK ────────────────────────────
    # SQLite quirk: CHECK нельзя ALTER'нуть, нужен table rebuild. Сохраняем
    # все данные через INSERT...SELECT.
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
                         CHECK (rarity IN ('common', 'rare', 'epic', 'legendary')),
            emoji        TEXT,
            svg_path     TEXT,
            deprecated   INTEGER NOT NULL DEFAULT 0,
            created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Copy existing data. Re-slot одновременно: шарф → body, очки → face.
    # Логика: items должны рендериться на правильных частях creature'а
    # (см. pet-stage.js anchor positions). accessory зарезервирован для
    # будущих side-companion items (мячик, шарик, питомец-маскот).
    await conn.execute("""
        INSERT INTO pet_catalog_new
            (item_id, name, slot, price_bits, rarity, emoji, svg_path,
             deprecated, created_at)
        SELECT
            item_id, name,
            CASE
                WHEN item_id = 'acc_scarf'   THEN 'body'
                WHEN item_id = 'acc_glasses' THEN 'face'
                ELSE slot
            END,
            price_bits, rarity, emoji, svg_path,
            deprecated, created_at
        FROM pet_catalog
    """)

    await conn.execute("DROP TABLE pet_catalog")
    await conn.execute("ALTER TABLE pet_catalog_new RENAME TO pet_catalog")

    # Воссоздать индекс
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_pet_catalog_active
            ON pet_catalog(slot, price_bits)
            WHERE deprecated = 0
    """)

    # ── 3. Migrate pet_equipped rows: scarf+glasses ушли в новые slots ────────
    # pet_equipped.slot без CHECK constraint — UPDATE достаточно.
    # PK = (username, slot): до миграции в 'body'/'face' ничего не было
    # (catalog не имел body/face items), конфликта PK не возникает.
    await conn.execute("""
        UPDATE pet_equipped SET slot = 'body'
        WHERE item_id = 'acc_scarf' AND slot = 'accessory'
    """)
    await conn.execute("""
        UPDATE pet_equipped SET slot = 'face'
        WHERE item_id = 'acc_glasses' AND slot = 'accessory'
    """)

    await conn.commit()
    await _mark_applied(conn, "M29.pets_slots_v2")
    print("✅ M29: pet_catalog rebuild + 6 slots + svg_path column + scarf→body")


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
