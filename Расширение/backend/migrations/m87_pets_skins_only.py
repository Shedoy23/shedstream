"""
Migration M87: магазин петов — только PNG-персонажи (body-skins), эмодзи убрать (2026-06-27).

Owner-решение: продавать не emoji-аксессуары, а PNG-«челиков» (character skins) — они
занимают body/грудь-слот и МЕНЯЮТ облик существа целиком. Эмодзи-косметика из M86
убирается из магазина (deprecated=1; owned-предметы у зрителей остаются валидны).

Рендер: pet-stage.js видит item_id с префиксом 'skin_' в body-слоте → меняет variant
существа на <name> (PNG из pet-assets/v2/<name>/{direction}.png), а не клеит overlay.

Добавить нового персонажа = положить pet-assets/v2/<name>/*.png (8 направлений) +
строку 'skin_<name>' в каталог (новой миграцией). Хардкод вариантов в pet-stage снят.

Идемпотентно: upsert по item_id + migrations_applied['M87.pets_skins_only'].
"""
# price_bits — legacy ordering-значение по редкости (цена реально из config по rarity)
_ORDER = {'common': 300, 'rare': 500, 'epic': 800, 'legendary': 1200, 'mythic': 2000}

# (item_id 'skin_<variant>', name, slot, rarity, png-превью для магазина)
# Цена берётся из config.PET_COSMETIC_PRICES по rarity. Рарность — стартовая,
# владелец крутит при генерации своих персонажей.
SKINS = [
    ('skin_underwear', 'Голый торс', 'body', 'common', 'pet-assets/v2/underwear/south.png'),
    ('skin_kimono',    'Кимоно',      'body', 'rare',   'pet-assets/v2/kimono/south.png'),
]


async def apply(conn) -> None:
    await _ensure_migrations_table(conn)
    if await _is_applied(conn, "M87.pets_skins_only"):
        return

    # 1. Убираем ВСЁ из магазина (emoji-косметику M86). owned-предметы остаются.
    await conn.execute("UPDATE pet_catalog SET deprecated = 1")

    # 2. Сидим/реактивируем PNG body-skins (персонажи).
    for item_id, name, slot, rarity, png in SKINS:
        await conn.execute(
            "INSERT INTO pet_catalog "
            "(item_id, name, slot, price_bits, rarity, emoji, png_path, deprecated) "
            "VALUES (?, ?, ?, ?, ?, NULL, ?, 0) "
            "ON CONFLICT(item_id) DO UPDATE SET "
            "  name=excluded.name, slot=excluded.slot, price_bits=excluded.price_bits, "
            "  rarity=excluded.rarity, png_path=excluded.png_path, deprecated=0",
            (item_id, name, slot, _ORDER[rarity], rarity, png)
        )

    await conn.commit()
    await _mark_applied(conn, "M87.pets_skins_only")
    print(f"✅ M87: pets shop = PNG skins only ({len(SKINS)} skins, emoji deprecated)")


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
