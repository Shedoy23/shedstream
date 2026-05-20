"""
Migration M30: pets catalog expansion (Sprint 5.22, 2026-05-20).

После M29 (6 slots) catalog был слабо заполнен — 5 items. Этот expansion
добавляет +15 emoji-items, доводя total до 20. Спрос на разнообразие
после redesign'a SVG creature: каждый slot теперь рендерится на правильной
части тела, юзеру хочется коллекционировать.

Цены — bits-tier scheme (текущая):
  common: 300 bits / rare: 500 bits / epic: 800 bits

Идемпотентно: INSERT OR IGNORE по PRIMARY KEY (item_id).
SVG art TBD — пока emoji-only. Когда нарисуем SVG для top-tier items
(корона, единорог, огненная аура), будет отдельный UPDATE-миграция по
svg_path колонке (см. M29 schema).

Item IDs: префиксы по slot для читаемости:
  hat_*  → head
  face_* → face
  body_* → body
  acc_*  → accessory
  bg_*   → background
  aura_* → aura
"""

# Sprint 5.22 expansion — 11 new items (после M32 cleanup'а 4 misfit items
# выкинуты из seed: hat_cowboy/face_mask/body_tie — их emoji содержат
# встроенное «лицо/торс» и плохо ложатся на blob creature'а).
CATALOG_ADDS = [
    # ── head (2 new) ──
    ('hat_top',         'Цилиндр',              'head',       500, 'rare',     '🎩'),
    ('hat_grad',        'Академическая шапочка', 'head',       500, 'rare',     '🎓'),
    # ── face (1 new) ──
    ('face_sunglasses', 'Тёмные очки',          'face',       500, 'rare',     '🕶️'),
    # ── body (1 new) ──
    ('body_bowtie',     'Бабочка',              'body',       500, 'rare',     '🦋'),
    # ── accessory (4 new) ──
    ('acc_balloon',     'Шарик',                'accessory',  300, 'common',   '🎈'),
    ('acc_ball',        'Мяч',                  'accessory',  300, 'common',   '⚽'),
    ('acc_gamepad',     'Геймпад',              'accessory',  500, 'rare',     '🎮'),
    ('acc_mic',         'Микрофон',             'accessory',  800, 'epic',     '🎤'),
    # ── background (2 new) ──
    ('bg_rainbow',      'Радуга',               'background', 800, 'epic',     '🌈'),
    ('bg_stars',        'Звёздное небо',        'background', 500, 'rare',     '⭐'),
    # ── aura (2 new — slot был пустой после M29) ──
    ('aura_fire',       'Огненная аура',        'aura',       800, 'epic',     '🔥'),
    ('aura_magic',      'Магическая аура',      'aura',       500, 'rare',     '✨'),
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M30.pets_catalog_expand"):
        return

    for item_id, name, slot, price, rarity, emoji in CATALOG_ADDS:
        await conn.execute(
            "INSERT OR IGNORE INTO pet_catalog "
            "(item_id, name, slot, price_bits, rarity, emoji) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (item_id, name, slot, price, rarity, emoji)
        )

    await conn.commit()
    await _mark_applied(conn, "M30.pets_catalog_expand")
    print(f"✅ M30: pets catalog +{len(CATALOG_ADDS)} items (total → 20)")


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
