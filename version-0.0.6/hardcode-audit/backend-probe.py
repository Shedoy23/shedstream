"""Read-only audit probe: actual store_catalog/buy_reason with SQLite :memory:."""
import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Расширение' / 'backend'))

import aiosqlite
from modules.bannerlord.equipment_shop import store_catalog, buy_reason, catalog


class DB:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def _connect(self):
        yield self.connection


async def main():
    async with aiosqlite.connect(':memory:') as connection:
        await connection.executescript("""
            CREATE TABLE bannerlord_channel_state(channel_id INTEGER,current_save_id TEXT);
            CREATE TABLE bannerlord_equipment_sessions(channel_id INTEGER,session_id TEXT);
            CREATE TABLE module_catalogs(channel_id INTEGER,module_id TEXT,catalog_type TEXT,entry_id TEXT,payload TEXT);
            INSERT INTO bannerlord_channel_state VALUES(1,'save');
            INSERT INTO bannerlord_equipment_sessions VALUES(1,'session');
        """)
        entries = [
            dict(item_id='mod_sword', tier=4, price_gold=100, required_level=1),
            dict(item_id='mod_tier7', tier=7, price_gold=100, required_level=1),
        ]
        await store_catalog(DB(connection), 1, SimpleNamespace(data=dict(
            entries=entries, save_id='save', equipment_session_id='session')))
        stored = await catalog(connection, 1)
        reason = buy_reason(stored[0], dict(reason=None, hero=['hero', 24, 10000]))
        assert len(stored) == 1, stored
        assert stored[0]['required_level'] == 25, stored
        assert reason == 'level_locked', reason
        print(json.dumps(dict(
            method='real functions, SQLite :memory:, no game or production DB',
            input=entries, stored=stored, hero_level=24,
            buy_reason=reason, result='PASS'), ensure_ascii=True, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
