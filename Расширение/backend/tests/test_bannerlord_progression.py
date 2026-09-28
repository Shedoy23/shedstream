"""Actor-owned game progression quotes; isolated SQLite, no live game."""
import asyncio
import json
import os
import tempfile
from pathlib import Path
from test_bannerlord_buy_action import _build_db, _make_anon_request, CHANNEL_ID


async def run(db):
    from routes import bannerlord as route
    from modules.bannerlord.equipment_shop import store_inventory
    from modules._base import ModuleEnvelope
    from modules.bannerlord._adapter import _cooldowns
    async def sql(q, args=()):
        async with db._connect() as conn:
            rows = await (await conn.execute(q,args)).fetchall()
            await conn.commit()
            return rows
    context = dict(save_id='save-a', equipment_session_id='session-a', hero_id='test_hero_alice')
    progression = dict(version=1, random_xp_available=True, random_xp_reason=None,
        skills=[dict(id='Mod.Skill',level=120,focus=2,focus_limit=9,native_focus_limit=11,xp_available=True,
            focus_options=[dict(amount=1,cost_gold=7,available=True),dict(amount=6,cost_gold=13,available=True)])],
        attributes=[dict(id='Mod.Attribute',value=4,limit=18,native_limit=20,
            options=[dict(amount=1,cost_gold=9,available=True),dict(amount=11,cost_gold=21,available=True)])])
    seq = 0
    async def publish(**changes):
        nonlocal seq
        seq += 1
        payload = dict(username='alice',inventory_seq=seq,items=[],build=None,progression=progression,**context)
        payload.update(changes)
        await store_inventory(db,CHANNEL_ID,ModuleEnvelope(id='snapshot',kind='event',type='hero.inventory_snapshot',ts=seq,data=payload))
    async def buy(kind, **data):
        _cooldowns.clear()
        return await route._bannerlord_buy_action_locked(_make_anon_request(),'alice',CHANNEL_ID,kind,data)
    async def finish():
        await sql("UPDATE module_actions SET status='acked'")
    def focus(**more):
        return dict(skill_key='Mod.Skill',amount=1,progression_context=context.copy(),expected_cost_gold=7,expected_value=2,**more)
    await sql("INSERT INTO bannerlord_channel_state(channel_id,current_save_id) VALUES(?,'save-a')",(CHANNEL_ID,))
    await sql("INSERT INTO bannerlord_equipment_sessions(channel_id,session_id,session_ts) VALUES(?,'session-a',1)",(CHANNEL_ID,))
    missing = await buy('hero.add_focus',**focus())
    assert missing.get('reason') == 'progression_not_ready', missing
    await publish()
    route.require_jwt_user=lambda request:('alice',CHANNEL_ID)
    response=await route.bannerlord_progression(_make_anon_request())
    assert response['ready'] and response['context']==context and response['progression']['skills'][0]['focus_limit']==9
    assert response['xp_offers'][0]['price']==500 and response['xp_offers'][0]['crusticov']==500
    # Game quote wins even if the backend's gold cache says zero; no duplicate formula.
    await sql("UPDATE bannerlord_heroes SET gold=0 WHERE channel_id=? AND username='alice'",(CHANNEL_ID,))
    result=await buy('hero.add_focus',**focus(_daily=True,target='victim',hero_id='evil',cost=0,price=999))
    assert result['success'] and result['charged']==0, result
    row=(await sql('SELECT data FROM module_actions WHERE action_id=?',(result['action_id'],)))[0][0]
    out=json.loads(row)
    assert out['skill_key']=='Mod.Skill' and out['expected_cost_gold']==7 and out['expected_value']==2
    assert out['target']=='alice' and out['hero_id']==context['hero_id'] and '_daily' not in out and 'cost' not in out
    await finish()
    # Published quantities are authoritative, not old 5/10 clamps.
    opts=focus(); opts.update(amount=6,expected_cost_gold=13)
    assert (await buy('hero.add_focus',**opts))['success']
    await finish()
    result=await buy('hero.add_attribute',attribute_key='Mod.Attribute',amount=11,progression_context=context,expected_cost_gold=21,expected_value=4)
    assert result['success'], result
    await finish()
    for mutation, reason in [(dict(expected_cost_gold=1),'progression_quote_changed'),(dict(expected_value=3),'progression_quote_changed'),
                              (dict(skill_key='mod.skill'),'progression_option_not_found'),(dict(amount=True),'progression_option_not_found'),
                              (dict(progression_context={**context,'hero_id':'other'}),'progression_changed')]:
        opts=focus();opts.update(mutation)
        denied=await buy('hero.add_focus',**opts)
        assert denied.get('reason')==reason,denied
    # Revalidate under the cash register transaction, with money and no queue on refusal.
    prepared=focus()
    assert await route._prepare_action('alice',CHANNEL_ID,'hero.add_focus',prepared) is None
    progression['skills'][0]['focus_options'][0]['available']=False
    progression['skills'][0]['focus_options'][0]['reason']='custom_blocked'
    await publish()
    before=(await sql("SELECT points FROM viewers WHERE channel_id=? AND username='alice'",(CHANNEL_ID,)))[0][0]
    count=(await sql('SELECT count(*) FROM module_actions'))[0][0]
    denied=await route._charge_execute_enqueue('hero.add_focus',prepared,500,'alice',CHANNEL_ID)
    assert denied.get('reason')=='custom_blocked',denied
    assert (await sql('SELECT count(*) FROM module_actions'))[0][0]==count
    assert (await sql("SELECT points FROM viewers WHERE channel_id=? AND username='alice'",(CHANNEL_ID,)))[0][0]==before
    # XP price/reward belongs to the backend, availability to the current game actor.
    denied=await buy('hero.add_skill',skill_key='Mod.Skill',price=500,expected_platform_price=1,progression_context=context)
    assert denied.get('reason')=='platform_price_changed',denied
    result=await buy('hero.add_skill',skill_key='Mod.Skill',price=500,expected_platform_price=500,progression_context=context,xp=999999,_daily=True)
    assert result['success'] and result['charged']==500,result
    out=json.loads((await sql('SELECT data FROM module_actions WHERE action_id=?',(result['action_id'],)))[0][0])
    assert out['xp']==50 and out['reward_boost']==1 and '_daily' not in out
    await finish()
    progression['skills'][0]['xp_available']=False; progression['skills'][0]['xp_reason']='skill_capped'
    await publish()
    assert (await buy('hero.add_skill',skill_key='Mod.Skill',price=500,expected_platform_price=500,progression_context=context))['reason']=='skill_capped'
    # Broadcaster pricing is quoted and charged consistently; retry/refund use actual 250.
    progression['skills'][0]['xp_available']=True
    await publish()
    import auth
    old_verify=auth.verify_twitch_jwt
    auth.verify_twitch_jwt=lambda request:dict(status='valid',role='broadcaster',user_id=str(CHANNEL_ID),channel_id=str(CHANNEL_ID))
    try:
        response=await route.bannerlord_progression(_make_anon_request())
        assert response['xp_offers'][0]['price']==250 and response['xp_offers'][0]['crusticov']==500
        before=(await sql("SELECT points FROM viewers WHERE channel_id=? AND username='alice'",(CHANNEL_ID,)))[0][0]
        args=dict(skill_key='Mod.Skill',price=500,expected_platform_price=250,progression_context=context,client_action_id='xp-role')
        result=await buy('hero.add_skill',**args)
        assert result['success'] and result['charged']==250,result
        out=json.loads((await sql('SELECT data FROM module_actions WHERE action_id=?',(result['action_id'],)))[0][0])
        assert out['xp']==50 and out['reward_boost']==2 and out['price']==250,out
        # Do not clear cooldown or finish the queued action for this real retry.
        replay=await route._bannerlord_buy_action_locked(_make_anon_request(),'alice',CHANNEL_ID,'hero.add_skill',args.copy())
        assert replay.get('idempotent_replay') and replay['action_id']==result['action_id'],replay
        from modules.bannerlord._adapter import BannerlordAdapter
        env=ModuleEnvelope(id=result['action_id'],kind='event',type='action.failed',ts=0,data=dict(action_id=result['action_id'],reason='test_refuse'))
        await BannerlordAdapter(None).handle_event(CHANNEL_ID,env)
        await BannerlordAdapter(None).handle_event(CHANNEL_ID,env)
        after=(await sql("SELECT points FROM viewers WHERE channel_id=? AND username='alice'",(CHANNEL_ID,)))[0][0]
        assert after==before,(before,after)
    finally:
        auth.verify_twitch_jwt=old_verify
    await finish()
    # Full replacement does not retain stale permission; old/wrong-session snapshots do not replace.
    await publish(progression={})
    await publish(equipment_session_id='old',progression=progression)
    assert not (await route.bannerlord_progression(_make_anon_request()))['ready']
    route.require_jwt_user=lambda request:('carol',CHANNEL_ID)
    assert not (await route.bannerlord_progression(_make_anon_request()))['ready']
    route.require_jwt_user=lambda request:None
    assert not (await route.bannerlord_progression(_make_anon_request()))['success']
    print('PASS progression game quote, exact IDs, limits, spoofing, atomic guards, XP price, identity/full replacement/auth')


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['DB_PATH']=str(Path(tmp)/'import.db')
        db=await _build_db(str(Path(tmp)/'test.db'))
        try:
            await run(db)
        finally:
            await db._pool.close()

if __name__=='__main__':
    asyncio.run(main())
