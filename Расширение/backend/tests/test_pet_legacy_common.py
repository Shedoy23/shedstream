"""Legacy skins: common/100000, preserving the 12 new skins and ownership."""
import ast,asyncio,sys
from pathlib import Path
from types import ModuleType
import aiosqlite

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
config=ModuleType('config')
for node in ast.parse((ROOT/'config.py').read_text(encoding='utf-8')).body:
    if isinstance(node,ast.Assign):
        for target in node.targets:
            if isinstance(target,ast.Name) and target.id in ('PET_COSMETIC_PRICES','PET_BASE_TYPE'):
                setattr(config,target.id,ast.literal_eval(node.value))
sys.modules['config']=config

async def main():
    from pet_collection import get_pet_price,COMPANIONS,FANTASY_COMPANIONS
    for item in ['skin_kimono','skin_underwear']:
        assert get_pet_price(item,'common')==100000,(item,get_pet_price(item,'common'))
        assert get_pet_price(item,'rare')==100000
    for variant in (*COMPANIONS,*FANTASY_COMPANIONS):
        assert get_pet_price('skin_'+variant,'rare')==500000
    assert get_pet_price('unrelated','common')==config.PET_COSMETIC_PRICES['common']
    from migrations import m133_pet_legacy_common as migration
    async with aiosqlite.connect(':memory:') as conn:
        await conn.executescript("""
        CREATE TABLE pet_catalog(item_id TEXT PRIMARY KEY,rarity TEXT,deprecated INTEGER);
        INSERT INTO pet_catalog VALUES('skin_kimono','rare',0),('skin_underwear','rare',0),('unrelated','epic',0);
        CREATE TABLE pet_inventory(username TEXT,item_id TEXT);
        INSERT INTO pet_inventory VALUES('owner','skin_kimono');
        CREATE TABLE pet_equipped(username TEXT,item_id TEXT);
        INSERT INTO pet_equipped VALUES('owner','skin_kimono');
        CREATE TABLE viewers(channel_id INTEGER,username TEXT,points INTEGER);
        INSERT INTO viewers VALUES(11,'owner',123456);
        """)
        before={t:await (await conn.execute('SELECT * FROM '+t)).fetchall() for t in ['pet_inventory','pet_equipped','viewers']}
        await migration.apply(conn); await migration.apply(conn)
        assert await (await conn.execute('SELECT item_id,rarity,deprecated FROM pet_catalog ORDER BY item_id')).fetchall()==[('skin_kimono','common',0),('skin_underwear','common',0),('unrelated','epic',0)]
        for t,rows in before.items():assert await (await conn.execute('SELECT * FROM '+t)).fetchall()==rows
        assert (await (await conn.execute('SELECT count(*) FROM migrations_applied')).fetchone())[0]==1
    from test_pet_collection_purchase import main as purchases
    for variant in (*COMPANIONS,*FANTASY_COMPANIONS):await purchases(variant)
    await purchases('lantern_mage',legacy='skin_underwear')
    print('PASS: both legacy purchases, idempotent rarity migration, owners/equips/balances unchanged, 13 purchase scenarios')

if __name__=='__main__':asyncio.run(main())
