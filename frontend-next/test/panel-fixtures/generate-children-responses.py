"""Child/heir/proposal contracts from real handlers; no live game or production."""
import asyncio,atexit,copy,json,os,sys,tempfile
from pathlib import Path
ROOT=Path(sys.argv[1]).resolve();sys.dont_write_bytecode=True
config_dir=tempfile.TemporaryDirectory(prefix='children-config-');atexit.register(config_dir.cleanup)
os.environ['RIMWORLD_PRICES_PATH']=str(Path(config_dir.name)/'unused.json')
sys.path[:0]=[str(ROOT/'Расширение/backend/tests'),str(ROOT/'Расширение/backend')]
from test_bannerlord_buy_action import _build_db,_make_anon_request,CHANNEL_ID
async def main():
    with tempfile.TemporaryDirectory(prefix='children-fixture-') as temporary:
        db=await _build_db(str(Path(temporary)/'fixture.db'))
        try:
            from routes import bannerlord as route,bannerlord_family as family
            from modules.bannerlord._adapter import _cooldowns
            import module_liveness
            request=_make_anon_request()
            for module in [route,family]:module.require_jwt_user=lambda _:('alice',CHANNEL_ID)
            await module_liveness.touch(db,CHANNEL_ID,'bannerlord')
            async def sql(q,args=()):
                async with db._connect() as conn:await conn.execute(q,args);await conn.commit()
            await sql("UPDATE bannerlord_heroes SET clan_name='Клан фикстуры' WHERE username='alice'")
            for owner,child,name in [('alice','child-a','Взрослый наследник'),('bob','child-b','Наследница Боба')]:
                await sql("INSERT INTO bannerlord_heirs(channel_id,parent_username,heir_hero_id,heir_name,alive,activated,came_of_age_at) VALUES(?,?,?,?,1,0,'2026-10-02 12:00:00')",(CHANNEL_ID,owner,child,name))
            out={'config':await route.bannerlord_config(),'children':await family.my_children(request),'heirs':await route.bannerlord_heirs(request),'proposals_empty':await family.proposals(request)}
            public_request=_make_anon_request();public_request.scope['query_string']=b'username=bob'
            out['public_children']=await family.public_children(public_request)
            async def buy(key,kind,data):
                _cooldowns.clear();await sql("UPDATE module_actions SET status='acked'")
                result=await route._bannerlord_buy_action_locked(request,'alice',CHANNEL_ID,kind,copy.deepcopy(data))
                if not isinstance(result,dict):result=json.loads(result.body)
                out[key]={'request':{'action_type':kind,'data':data},'response':result};return result
            assert (await buy('rename','hero.rename_child',dict(child_hero_id='child-a',new_name=' Новое имя ')))['success']
            assert (await buy('looks','hero.change_child_looks',dict(child_hero_id='child-a',body_code='fixture-body-properties')))['success']
            assert (await buy('respec','hero.respec_child_skills',dict(child_hero_id='child-a')))['success']
            assert not (await buy('rename_refused','hero.rename_child',dict(child_hero_id='child-b',new_name='Wrong owner')))['success']
            assert (await buy('propose','hero.propose_marriage',dict(price=out['config']['action_prices']['hero.propose_marriage'],proposer_child_hero_id='child-a',target_username='bob',target_child_hero_id='child-b')))['success']
            await sql("INSERT INTO bannerlord_marriage_proposals(id,channel_id,proposer_username,proposer_child_hero_id,proposer_child_name,target_username,target_child_hero_id,target_child_name,expires_at) VALUES(200,?,'bob','child-b','Наследница Боба','alice','child-a','Взрослый наследник',datetime('now','+1 day'))",(CHANNEL_ID,))
            out['proposals']=await family.proposals(request)
            for accept in [True,False]:
                await sql("UPDATE bannerlord_marriage_proposals SET status='pending' WHERE id=200")
                assert (await buy('accept' if accept else 'reject','hero.respond_marriage_proposal',dict(proposal_id=200,accept=accept)))['success']
            assert not (await buy('respond_refused','hero.respond_marriage_proposal',dict(proposal_id=200,accept=True)))['success']
            outgoing=out['proposals']['outgoing'][0]['id'];out['outgoing_id']=outgoing
            assert (await buy('cancel','hero.cancel_proposal',dict(proposal_id=outgoing)))['success']
            Path(__file__).with_name('children-responses.json').write_text(json.dumps({'provenance':{'base':'107bbe3','database':'owned temporary SQLite','live_game':False,'synthetic':'owned heir/proposal rows, body code is queue-only fixture'},'responses':out},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print('CHILDREN_FIXTURES_OK',len(out))
        finally:await db._pool.close()
asyncio.run(main())
