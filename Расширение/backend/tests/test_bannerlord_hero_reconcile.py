"""Real SQLite regression: save-owned identities must reconcile atomically."""
import asyncio
import sqlite3
import tempfile
from pathlib import Path
from test_bannerlord_buy_action import _build_db, _make_anon_request, CHANNEL_ID


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = await _build_db(str(Path(tmp) / 'heroes.db'))
        try:
            from modules.bannerlord._adapter import BannerlordAdapter
            from modules._base import ModuleEnvelope
            from modules.bannerlord.equipment_shop import store_inventory
            from routes import bannerlord as route
            adapter = BannerlordAdapter(None)

            async def sql(query, args=()):
                async with db._connect() as conn:
                    cur = await conn.execute(query, args)
                    rows = await cur.fetchall()
                    await conn.commit()
                    return rows

            async def reconcile(heroes, save='save-a'):
                await adapter.handle_event(CHANNEL_ID, ModuleEnvelope(id='heroes', kind='event',
                    type='module.heroes_snapshot', ts=2, data={'save_id': save, 'heroes': heroes}))

            await sql("INSERT INTO bannerlord_channel_state(channel_id,current_save_id) VALUES(?,'save-a')", (CHANNEL_ID,))
            await sql("INSERT INTO bannerlord_equipment_sessions(channel_id,session_id,session_ts) VALUES(?,'session-a',1)", (CHANNEL_ID,))
            await sql("INSERT INTO bannerlord_heroes(channel_id,username,hero_id,display_name) VALUES(?,'stale','occupied','Old')", (CHANNEL_ID,))
            await sql("INSERT INTO bannerlord_heroes(channel_id,username,hero_id,display_name) VALUES(?,'untouched','occupied','Other channel')", (CHANNEL_ID+1,))
            await sql("UPDATE bannerlord_heroes SET is_alive=0,level=32 WHERE channel_id=? AND username='alice'", (CHANNEL_ID,))
            heroes = [{'username':'alice','hero_id':'occupied'}, {'username':'carol','hero_id':'test_hero_alice'}]
            await reconcile(heroes)
            assert await sql('SELECT username,hero_id,is_alive,level,gold FROM bannerlord_heroes WHERE channel_id=? ORDER BY username', (CHANNEL_ID,)) == [
                ('alice','occupied',1,32,500000), ('carol','test_hero_alice',1,1,0)], 'Restore missing viewers, keep progress, and revive heroes present in the save'
            # Cyclic reassignment cannot be solved by deleting only absent viewers.
            await reconcile([{'username':'alice','hero_id':'test_hero_alice'}, {'username':'carol','hero_id':'occupied'}])
            before = await sql('SELECT * FROM bannerlord_heroes WHERE channel_id=? ORDER BY username', (CHANNEL_ID,))
            await reconcile([{'username':'wrong','hero_id':'other'}], save='previous-save')
            assert await sql('SELECT * FROM bannerlord_heroes WHERE channel_id=? ORDER BY username', (CHANNEL_ID,)) == before, 'Late snapshot from another save must not replace current heroes'
            try:
                await reconcile([{'username':'alice','hero_id':'duplicate'}, {'username':'carol','hero_id':'duplicate'}])
            except ValueError:
                pass
            else:
                raise AssertionError('Ambiguous snapshot must be rejected')
            assert await sql('SELECT * FROM bannerlord_heroes WHERE channel_id=? ORDER BY username', (CHANNEL_ID,)) == before, 'Invalid snapshot must leave the entire roster untouched'
            # A storage failure after temporary ids were installed must also roll
            # back, not leave invisible placeholders in a pooled connection.
            await sql("CREATE TRIGGER fail_reconcile_all BEFORE INSERT ON bannerlord_heroes WHEN NEW.username='carol' BEGIN SELECT RAISE(ABORT,'injected failure'); END")
            try:
                await reconcile(heroes)
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError('Injected storage failure did not run')
            assert await sql('SELECT * FROM bannerlord_heroes WHERE channel_id=? ORDER BY username', (CHANNEL_ID,)) == before, 'Storage failure must roll back identity reassignment'
            await sql('DROP TRIGGER fail_reconcile_all')
            assert await sql('SELECT hero_id FROM bannerlord_heroes WHERE channel_id=?', (CHANNEL_ID+1,)) == [('occupied',)]
            route.require_jwt_user = lambda req: ('alice', CHANNEL_ID)
            async def inventory(seq, **extra):
                await store_inventory(db, CHANNEL_ID, ModuleEnvelope(id='inventory', kind='event', type='hero.inventory_snapshot', ts=seq,
                    data=dict(username='alice',hero_id='test_hero_alice',save_id='save-a',equipment_session_id='session-a',inventory_seq=seq,items=[],**extra)))
            await inventory(1, build=None)  # Explicit game-owned legacy marker, not missing transport data.
            response = await route.bannerlord_build(_make_anon_request())
            assert response['reason'] == 'legacy_build' and not response['ready'], response
            assert 'нов' in response['message'] and not response['can_manage'], response
            await inventory(2)  # Missing field must never be interpreted as a legacy hero.
            response = await route.bannerlord_build(_make_anon_request())
            assert response['reason'] == 'build_not_ready', response
            print('PASS hero reconciliation: occupied ids, cyclic ids, missing viewers, progress, alive state, wrong save, rollback, tenant isolation, legacy build vs missing data')
        finally:
            await db._pool.close()


if __name__ == '__main__':
    asyncio.run(main())
