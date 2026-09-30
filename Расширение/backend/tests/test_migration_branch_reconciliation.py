"""Both independently named M129/M130 lines must survive either upgrade order."""
import asyncio
import importlib
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from contextlib import ExitStack

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TEMP = tempfile.TemporaryDirectory(prefix='branch_migrations_')
os.environ['DB_PATH'] = str(Path(TEMP.name) / 'unused.sqlite')
for key, value in {'TWITCH_OAUTH_TOKEN': 'test', 'TWITCH_CLIENT_ID': 'test',
                   'TWITCH_CLIENT_SECRET': 'test', 'TWITCH_BOT_ID': '1',
                   'TWITCH_BROADCASTER_ID': '98319857', 'TWITCH_CHANNEL_NAME': 'test',
                   'MODULE_TOKEN_SECRET': 'test', 'ADMIN_PASSWORD': 'test'}.items():
    os.environ.setdefault(key, value)

GROUPS = {
    'main': ['m129_reforge_rights', 'm130_clan_catalog_truth',
             'm131_daily_claim_action', 'm132_module_actions_recent_index'],
    'pets': ['m129_pet_companions', 'm130_pet_fantasy', 'm133_pet_legacy_common'],
}
MARKERS = {'M129.reforge_rights', 'M130.clan_catalog_truth',
           'M129.pet_companions', 'M130.pet_fantasy', 'M133.pet_legacy_common'}

async def skip(_conn):
    pass

async def main():
    import aiosqlite
    from database import Database
    import main as app
    for initial in ('fresh', 'main', 'pets'):
        db = Database(str(Path(TEMP.name) / (initial + '.sqlite')))
        app.db = db
        try:
            await db.init_tables()
            missing = (GROUPS['main'] + GROUPS['pets'] if initial == 'fresh'
                       else GROUPS['pets' if initial == 'main' else 'main'])
            with ExitStack() as stack:
                for name in missing:
                    stack.enter_context(patch.object(importlib.import_module('migrations.' + name), 'apply', skip))
                await app.run_migrations()
            # Simulate an existing owner before the two branches are reconciled.
            async with aiosqlite.connect(db.db_path) as conn:
                await conn.execute("INSERT INTO viewers(channel_id,username,points) VALUES(11,'merge_viewer',1000000)")
                await conn.execute("INSERT INTO pet_inventory(username,item_id) VALUES('merge_viewer','skin_kimono')")
                await conn.execute("INSERT INTO pet_equipped(username,slot,item_id) VALUES('merge_viewer','body','skin_kimono')")
                await conn.commit()
            await app.run_migrations()
            async with aiosqlite.connect(db.db_path) as conn:
                rows = await (await conn.execute('SELECT name FROM migrations_applied')).fetchall()
                assert MARKERS <= {r[0] for r in rows}, (initial, MARKERS - {r[0] for r in rows})
                assert len(rows) == len(set(rows)), 'duplicate migration identities'
                assert await (await conn.execute("SELECT points FROM viewers WHERE username='merge_viewer'")).fetchone() == (1000000,)
                assert await (await conn.execute("SELECT item_id FROM pet_equipped WHERE username='merge_viewer'")).fetchone() == ('skin_kimono',)
                catalog = await (await conn.execute("SELECT item_id FROM pet_catalog WHERE deprecated=0 AND item_id LIKE 'skin_%'")).fetchall()
                assert len(catalog) == 14, (initial, catalog)
            result = await db.purchase_pet_item('merge_viewer', 'skin_wayfarer', 11)
            assert result.get('purchased') and result['price'] == 500000, result
            await app.run_migrations()
            async with aiosqlite.connect(db.db_path) as conn:
                assert await (await conn.execute("SELECT points FROM viewers WHERE username='merge_viewer'")).fetchone() == (500000,)
                assert await (await conn.execute("SELECT item_id FROM pet_equipped WHERE username='merge_viewer'")).fetchone() == ('skin_wayfarer',)
                assert await (await conn.execute("SELECT COUNT(*) FROM pet_inventory WHERE username='merge_viewer'")).fetchone() == (2,)
                assert await (await conn.execute("SELECT COUNT(*) FROM pet_purchases WHERE username='merge_viewer'")).fetchone() == (1,)
            print('PASS:', initial, 'upgrade, both migration identities, ownership, purchase, replay')
        finally:
            if getattr(db, '_pool', None):
                await db._pool.close()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    finally:
        TEMP.cleanup()
