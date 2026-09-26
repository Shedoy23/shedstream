"""Developer-owned companion collection; shared display and charge prices."""

COMPANIONS = {
    'wayfarer': 'Странник',
    'crimson_knight': 'Багряный рыцарь',
    'colony_engineer': 'Инженер',
    'lantern_mage': 'Сонный колдунчик',
    'shadow_rogue': 'Разбойник',
    'rain_fisher': 'Рыбак',
}
COLLECTION_PRICE = 500_000


def get_pet_price(item_id, rarity):
    from config import PET_COSMETIC_PRICES
    if item_id in {f'skin_{variant}' for variant in COMPANIONS}:
        return COLLECTION_PRICE
    return PET_COSMETIC_PRICES.get(rarity, PET_COSMETIC_PRICES['common'])


async def seed_collection(conn):
    """Add only these six skins. Existing catalog/ownership stays intact."""
    for variant, name in COMPANIONS.items():
        await conn.execute(
            'INSERT INTO pet_catalog '
            '(item_id,name,slot,price_bits,rarity,emoji,png_path,deprecated) '
            "VALUES (?,?,'body',500,'rare',NULL,?,0) "
            'ON CONFLICT(item_id) DO NOTHING',
            (f'skin_{variant}', name, f'pet-assets/v2/{variant}/south.png'),
        )

