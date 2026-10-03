"""Merged route responses on an owned temporary DB; simulated game metadata only."""
import asyncio, atexit, copy, json, os, sys, tempfile
from pathlib import Path
ROOT = Path(sys.argv[1]).resolve()
OUT = Path(__file__).parent
sys.dont_write_bytecode = True
temporary_config = tempfile.TemporaryDirectory(prefix='progression-fixture-config-')
atexit.register(temporary_config.cleanup)
os.environ['RIMWORLD_PRICES_PATH'] = str(Path(temporary_config.name) / 'unused.json')
sys.path[:0] = [str(ROOT / 'Расширение/backend/tests'), str(ROOT / 'Расширение/backend')]
from test_bannerlord_buy_action import _build_db, _make_anon_request, CHANNEL_ID

async def main():
    original = json.loads((OUT / 'real-responses.json').read_text(encoding='utf-8'))['responses']['hero']
    with tempfile.TemporaryDirectory(prefix='progression-fixture-db-') as temporary:
        db = await _build_db(str(Path(temporary) / 'fixture.db'))
        try:
            from routes import bannerlord as route
            from modules.bannerlord.equipment_shop import store_inventory
            from modules.bannerlord.content_catalogs import store_catalog
            from modules.bannerlord._adapter import _cooldowns
            from modules._base import ModuleEnvelope
            import module_liveness
            request = _make_anon_request()
            route.require_jwt_user = lambda _: ('alice', CHANNEL_ID)
            async def sql(query, args=()):
                async with db._connect() as conn:
                    await conn.execute(query, args)
                    await conn.commit()
            await module_liveness.touch(db, CHANNEL_ID, 'bannerlord')
            await sql("INSERT INTO bannerlord_channel_state(channel_id,current_save_id) VALUES(?,'save-a')", (CHANNEL_ID,))
            await sql("INSERT INTO bannerlord_equipment_sessions(channel_id,session_id,session_ts) VALUES(?,'session-a',1)", (CHANNEL_ID,))
            context = dict(save_id='save-a', equipment_session_id='session-a', hero_id='test_hero_alice')
            responses = {'catalogs_missing': await route.bannerlord_content_catalogs(request),
                         'progression_missing': await route.bannerlord_progression(request)}
            attributes = [dict(id=key.lower(), value=value, limit=14, native_limit=17,
                              options=[dict(amount=1, cost_gold=17 + index, available=True)])
                          for index, (key, value) in enumerate(original['attributes'].items())]
            skills = [dict(id=s['skill_key'], level=s['level'], focus=s['focus'], focus_limit=9, native_focus_limit=11,
                           xp_available=True, focus_options=[dict(amount=1, cost_gold=7 + i, available=True)])
                      for i, s in enumerate(original['skills'])]
            game = dict(version=1, random_xp_available=True, skills=skills, attributes=attributes)
            seq = 0
            async def publish(value):
                nonlocal seq
                seq += 1
                await store_inventory(db, CHANNEL_ID, ModuleEnvelope(id='fixture-inventory', kind='event', type='hero.inventory_snapshot', ts=seq,
                    data=dict(username='alice', inventory_seq=seq, items=[], build=None, progression=value, **context)))
            for kind, entries in {
                'cultures': [dict(id='Mod.Culture-X', name='Культура из игры', description='Описание из игрового каталога', available=True),
                             dict(id='NoTemplate', name='Недоступная культура', available=False, unavailable_reason='culture_no_wanderer_templates')],
                'workshop_types': [dict(id='Mod.Workshop-X', name='Мастерская из игры', description='Тип из WorkshopType.All')],
                'skills': [dict(id=s['id'], name=s['id'], description='Описание навыка из игры') for s in skills],
                'attributes': [dict(id=a['id'], name=a['id'], description='Описание атрибута из игры') for a in attributes],
                'policies': [dict(id='Mod.Policy-X', name='Закон из игры', description='Текст закона из игры')],
            }.items():
                await store_catalog(db, CHANNEL_ID, dict(catalog=kind, catalog_seq=1, entries=entries,
                    save_id=context['save_id'], equipment_session_id=context['equipment_session_id']))
            await publish(game)
            responses['catalogs'] = await route.bannerlord_content_catalogs(request)
            responses['progression'] = await route.bannerlord_progression(request)
            async def buy(label, kind, data):
                _cooldowns.clear()
                response = await route._bannerlord_buy_action_locked(request, 'alice', CHANNEL_ID, kind, copy.deepcopy(data))
                responses[label] = {'request': {'action_type': kind, 'data': data}, 'response': response if isinstance(response, dict) else json.loads(response.body)}
                return responses[label]['response']
            focus = dict(skill_key=skills[0]['id'], amount=1, expected_cost_gold=skills[0]['focus_options'][0]['cost_gold'], expected_value=skills[0]['focus'], progression_context=context)
            assert (await buy('focus_success', 'hero.add_focus', focus))['success']
            responses['progression_pending'] = await route.bannerlord_progression(request)
            await sql("UPDATE module_actions SET status='acked'")
            attribute = dict(attribute_key=attributes[0]['id'], amount=1, expected_cost_gold=attributes[0]['options'][0]['cost_gold'], expected_value=attributes[0]['value'], progression_context=context)
            assert (await buy('attribute_success', 'hero.add_attribute', attribute))['success']
            await sql("UPDATE module_actions SET status='acked'")
            offer = responses['progression']['xp_offers'][0]
            assert (await buy('xp_success', 'hero.add_skill', dict(price=offer['crusticov'], expected_platform_price=offer['price'], progression_context=context)))['success']
            await sql("UPDATE module_actions SET status='acked'")
            assert not (await buy('quote_changed', 'hero.add_focus', {**focus, 'expected_cost_gold': 999}))['success']
            assert not (await buy('context_changed', 'hero.add_focus', {**focus, 'progression_context': {**context, 'hero_id': 'other'}}))['success']
            mod_game = dict(version=1, random_xp_available=True,
                skills=[dict(id='Mod.Skill', level=401, focus=7, focus_limit=9, native_focus_limit=11, xp_available=True,
                    focus_options=[dict(amount=1, cost_gold=0, available=True)])],
                attributes=[dict(id='Mod.Attribute', value=12, limit=18, native_limit=20,
                    options=[dict(amount=1, cost_gold=9, available=True)])])
            await publish(mod_game)
            responses['progression_mod'] = await route.bannerlord_progression(request)
            assert responses['progression']['ready'] and responses['catalogs']['workshop_types']['available']
            assert [e['id'] for e in responses['catalogs']['cultures']['entries']] == ['Mod.Culture-X']
            (OUT / 'game-progression-responses.json').write_text(json.dumps({'provenance': {
                'base_merge': 'e66e82098f894bc8f6e0dbe9598ddf2516088636',
                'handlers': ['routes.bannerlord.bannerlord_content_catalogs', 'routes.bannerlord.bannerlord_progression', 'routes.bannerlord._bannerlord_buy_action_locked'],
                'database': 'owned temporary SQLite, full merged migrations', 'live_game': False,
                'metadata': 'representative simulated game snapshots through real store_catalog/store_inventory; never frontend defaults'
            }, 'responses': responses}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print('PROGRESSION_FIXTURES_OK', len(responses), 'real responses; no production requests')
        finally:
            await db._pool.close()
asyncio.run(main())
