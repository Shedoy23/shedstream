"""Execute the real purchase method against SQLite, without booting the bot."""
import ast
import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict
from types import ModuleType

import aiosqlite

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main(variant='lantern_mage'):
    config = ModuleType('config')
    for node in ast.parse((ROOT / 'config.py').read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ('PET_COSMETIC_PRICES', 'PET_BASE_TYPE'):
                    setattr(config, target.id, ast.literal_eval(node.value))
    sys.modules['config'] = config
    from pet_collection import COMPANIONS, get_pet_price
    assert len(COMPANIONS) == 6
    assert all(get_pet_price('skin_' + x, 'rare') == 500000 for x in COMPANIONS)
    assert get_pet_price('skin_kimono', 'rare') == 1000000
    # Execute the actual catalog route to prove display and charge agree.
    route_tree = ast.parse((ROOT / 'routes/pets.py').read_text(encoding='utf-8'))
    route = next(n for n in route_tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'pet_catalog')
    route.decorator_list = []
    class CatalogDB:
        async def list_pet_catalog(self, include_owned=None):
            return [{'item_id': 'skin_' + k, 'rarity': 'rare'} for k in COMPANIONS] + [{'item_id':'skin_kimono','rarity':'rare'}]
    rn = {'Request':object,'require_jwt_user':lambda _:None,'get_db':CatalogDB,'get_pet_price':get_pet_price}
    exec(compile(ast.Module(body=[route],type_ignores=[]),'routes/pets.py','exec'),rn)
    catalog = await rn['pet_catalog'](object())
    assert [x['price_crustics'] for x in catalog['items']] == [500000]*6+[1000000]
    tree = ast.parse((ROOT / 'database.py').read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Database')
    method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'purchase_pet_item')
    ns = {'Dict': Dict}
    exec(compile(ast.Module(body=[method], type_ignores=[]), 'database.py', 'exec'), ns)
    async with aiosqlite.connect(':memory:') as conn:
        await conn.executescript(f'''
        CREATE TABLE pet_catalog(item_id TEXT PRIMARY KEY, rarity TEXT, slot TEXT, deprecated INTEGER);
        CREATE TABLE viewers(channel_id INTEGER, username TEXT, points INTEGER, PRIMARY KEY(channel_id,username));
        CREATE TABLE pets(username TEXT PRIMARY KEY, pet_type TEXT);
        CREATE TABLE pet_inventory(username TEXT,item_id TEXT,PRIMARY KEY(username,item_id));
        CREATE TABLE pet_equipped(username TEXT,slot TEXT,item_id TEXT,equipped_at TEXT,PRIMARY KEY(username,slot));
        CREATE TABLE pet_purchases(id INTEGER PRIMARY KEY,username TEXT,item_id TEXT,channel_id INTEGER,bits_amount INTEGER,bits_receipt TEXT,mode TEXT);
        INSERT INTO pet_catalog VALUES('skin_{variant}','rare','body',0),('skin_kimono','rare','body',0);
        INSERT INTO viewers VALUES(11,'alice',500000),(22,'alice',2000000),(11,'bob',499999);
        ''')
        class DB:
            @asynccontextmanager
            async def _connect(self):
                yield conn
        purchase = ns['purchase_pet_item']
        item_id = 'skin_' + variant
        result = await purchase(DB(), 'Alice', item_id, 11)
        assert result.get('purchased') and result['price'] == 500000, f'new rare pet must cost 500000: {result}'
        assert await (await conn.execute('SELECT channel_id,points FROM viewers WHERE username="alice" ORDER BY channel_id')).fetchall() == [(11,0),(22,2000000)]
        assert await (await conn.execute('SELECT item_id FROM pet_equipped WHERE username="alice"')).fetchone() == (item_id,)
        assert (await purchase(DB(),'alice',item_id,22))['reason'] == 'already_owned'
        assert (await purchase(DB(),'bob',item_id,11))['reason'] == 'insufficient_crustics'
        assert await (await conn.execute('SELECT points FROM viewers WHERE username="bob"')).fetchone() == (499999,)
        old = await purchase(DB(),'alice','skin_kimono',22)
        assert old.get('purchased') and old['price'] == 1000000, old
        assert await (await conn.execute('SELECT bits_amount FROM pet_purchases ORDER BY id')).fetchall() == [(500000,),(1000000,)]
        assert (await purchase(DB(),'bob','skin_missing',11))['reason'] == 'item_not_found'
    from migrations import m129_pet_companions
    async with aiosqlite.connect(':memory:') as conn:
        await conn.execute('CREATE TABLE pet_catalog(item_id TEXT PRIMARY KEY,name TEXT,slot TEXT,price_bits INTEGER,rarity TEXT,emoji TEXT,png_path TEXT,deprecated INTEGER)')
        await conn.execute("INSERT INTO pet_catalog VALUES('skin_kimono','Кимоно','body',500,'rare',NULL,'old.png',0)")
        await conn.commit()
        await m129_pet_companions.apply(conn)
        await m129_pet_companions.apply(conn)
        rows=await (await conn.execute('SELECT item_id,rarity FROM pet_catalog')).fetchall()
        assert len(rows)==7 and all(r[1]=='rare' for r in rows)
        assert await (await conn.execute("SELECT png_path FROM pet_catalog WHERE item_id='skin_kimono'")).fetchone()==('old.png',)
    print('PASS: exact price, auto-equip, insufficient funds, duplicate, channel isolation, old prices, audit')


if __name__ == '__main__':
    asyncio.run(main())
