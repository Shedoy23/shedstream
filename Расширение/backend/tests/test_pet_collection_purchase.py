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


async def main():
    config = ModuleType('config')
    for node in ast.parse((ROOT / 'config.py').read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ('PET_COSMETIC_PRICES', 'PET_BASE_TYPE'):
                    setattr(config, target.id, ast.literal_eval(node.value))
    sys.modules['config'] = config
    tree = ast.parse((ROOT / 'database.py').read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Database')
    method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'purchase_pet_item')
    ns = {'Dict': Dict}
    exec(compile(ast.Module(body=[method], type_ignores=[]), 'database.py', 'exec'), ns)
    async with aiosqlite.connect(':memory:') as conn:
        await conn.executescript('''
        CREATE TABLE pet_catalog(item_id TEXT PRIMARY KEY, rarity TEXT, slot TEXT, deprecated INTEGER);
        CREATE TABLE viewers(channel_id INTEGER, username TEXT, points INTEGER, PRIMARY KEY(channel_id,username));
        CREATE TABLE pets(username TEXT PRIMARY KEY, pet_type TEXT);
        CREATE TABLE pet_inventory(username TEXT,item_id TEXT,PRIMARY KEY(username,item_id));
        CREATE TABLE pet_equipped(username TEXT,slot TEXT,item_id TEXT,equipped_at TEXT,PRIMARY KEY(username,slot));
        CREATE TABLE pet_purchases(id INTEGER PRIMARY KEY,username TEXT,item_id TEXT,channel_id INTEGER,bits_amount INTEGER,bits_receipt TEXT,mode TEXT);
        INSERT INTO pet_catalog VALUES('skin_lantern_mage','rare','body',0),('skin_kimono','rare','body',0);
        INSERT INTO viewers VALUES(11,'alice',500000),(22,'alice',2000000),(11,'bob',499999);
        ''')
        class DB:
            @asynccontextmanager
            async def _connect(self):
                yield conn
        purchase = ns['purchase_pet_item']
        result = await purchase(DB(), 'Alice', 'skin_lantern_mage', 11)
        assert result.get('purchased') and result['price'] == 500000, f'new rare pet must cost 500000: {result}'
        assert await (await conn.execute('SELECT channel_id,points FROM viewers WHERE username="alice" ORDER BY channel_id')).fetchall() == [(11,0),(22,2000000)]
        assert await (await conn.execute('SELECT item_id FROM pet_equipped WHERE username="alice"')).fetchone() == ('skin_lantern_mage',)
        assert (await purchase(DB(),'alice','skin_lantern_mage',22))['reason'] == 'already_owned'
        assert (await purchase(DB(),'bob','skin_lantern_mage',11))['reason'] == 'insufficient_crustics'
        assert await (await conn.execute('SELECT points FROM viewers WHERE username="bob"')).fetchone() == (499999,)
        old = await purchase(DB(),'alice','skin_kimono',22)
        assert old.get('purchased') and old['price'] == 1000000, old
        assert await (await conn.execute('SELECT bits_amount FROM pet_purchases ORDER BY id')).fetchall() == [(500000,),(1000000,)]
        assert (await purchase(DB(),'bob','skin_missing',11))['reason'] == 'item_not_found'
    print('PASS: exact price, auto-equip, insufficient funds, duplicate, channel isolation, old prices, audit')


if __name__ == '__main__':
    asyncio.run(main())
