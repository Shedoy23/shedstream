"""
Migration M86: re-seed pet cosmetics catalog (2026-06-27).

M37 (clean slate) обнулил каталог, а предметы заново не добавили → магазин петов
оказался пустым. Заодно сменили монетизацию: косметика покупается за КРУСТИКИ по
редкости (config.PET_COSMETIC_PRICES), Bits выпилены.

Цена НЕ хранится в каталоге — берётся из конфига по `rarity`; колонка `price_bits`
(NOT NULL) заполняется ordering-значением по редкости (для ORDER BY в list_pet_catalog).

Предметы — emoji-only (рендерятся по emoji, спрайтов у косметики нет). Детерминированы,
задаются ТУТ (не стримером) — compliance §6.2.8.

Идемпотентно: INSERT OR IGNORE по item_id + migrations_applied['M86.pets_reseed_crustics'].
"""

# price_bits — legacy ordering-значение по редкости (цена реально из config по rarity)
_ORDER = {'common': 300, 'rare': 500, 'epic': 800, 'legendary': 1200, 'mythic': 2000}

# (item_id, name, slot, rarity, emoji)
CATALOG = [
    # common (500к)
    ('hat_cap',         'Кепка',                  'head',       'common',    '🧢'),
    ('acc_glasses',     'Очки',                   'accessory',  'common',    '👓'),
    ('acc_balloon',     'Шарик',                  'accessory',  'common',    '🎈'),
    ('acc_ball',        'Мяч',                    'accessory',  'common',    '⚽'),
    # rare (1кк)
    ('acc_scarf',       'Шарф',                   'accessory',  'rare',      '🧣'),
    ('bg_violet',       'Фиолетовый фон',         'background', 'rare',      '🟣'),
    ('hat_top',         'Цилиндр',                'head',       'rare',      '🎩'),
    ('hat_grad',        'Академическая шапочка',   'head',       'rare',      '🎓'),
    ('face_sunglasses', 'Тёмные очки',            'face',       'rare',      '🕶️'),
    ('body_bowtie',     'Бабочка',                'body',       'rare',      '🦋'),
    ('acc_gamepad',     'Геймпад',                'accessory',  'rare',      '🎮'),
    ('bg_stars',        'Звёздное небо',          'background', 'rare',      '⭐'),
    ('aura_magic',      'Магическая аура',         'aura',       'rare',      '✨'),
    # epic (2кк)
    ('acc_mic',         'Микрофон',               'accessory',  'epic',      '🎤'),
    ('bg_rainbow',      'Радуга',                 'background', 'epic',      '🌈'),
    ('aura_fire',       'Огненная аура',           'aura',       'epic',      '🔥'),
    # legendary (3.5кк)
    ('hat_crown',       'Корона',                 'head',       'legendary', '👑'),
    ('hat_unicorn',     'Единорог',               'head',       'legendary', '🦄'),
    # mythic (5кк)
    ('aura_galaxy',     'Галактическая аура',      'aura',       'mythic',    '🌌'),
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M86.pets_reseed_crustics"):
        return

    for item_id, name, slot, rarity, emoji in CATALOG:
        await conn.execute(
            "INSERT OR IGNORE INTO pet_catalog "
            "(item_id, name, slot, price_bits, rarity, emoji) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (item_id, name, slot, _ORDER[rarity], rarity, emoji)
        )

    await conn.commit()
    await _mark_applied(conn, "M86.pets_reseed_crustics")
    print(f"✅ M86: pets catalog re-seeded ({len(CATALOG)} items, крустики-pricing)")


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
