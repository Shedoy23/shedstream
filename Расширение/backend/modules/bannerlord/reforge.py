"""Paid reforge rights are separate from observed game equipment."""
import json

async def validate_tx(conn, channel_id, username, data):
    from .equipment_shop import context
    ctx = await context(conn, channel_id, username)
    if ctx['reason']:
        return {'success':False,'message':'Снаряжение ещё не синхронизировано: обнови мод и дождись загрузки.'}
    slot=str(data.get('slot') or '').lower()
    item=next((r for r in ctx['inventory'] if r.get('slot')==slot and r.get('source')=='equipped'),None)
    if not item or not item.get('reforge_options'):
        return {'success':False,'message':'Для перековки обнови мод и дождись снимка надетого предмета.'}
    key=(channel_id,ctx['save_id'],ctx['hero'][0],username,slot,item['item_id'])
    row=await (await conn.execute("SELECT MAX(rank) FROM bannerlord_reforge_rights WHERE channel_id=? AND save_id=? AND hero_id=? AND username=? AND slot=? AND item_id=? AND state IN ('pending','active')",key)).fetchone()
    current=int(item.get('quality_rank') or 0)
    if row and row[0] is not None and row[0]>current:
        return {'success':False,'message':'Оплаченное качество восстанавливается. Дождись синхронизации; повторно платить не нужно.'}
    options=[r for r in item['reforge_options'] if int(r['rank'])>current]
    if not options:
        return {'success':False,'message':'Предмет уже лучшего доступного качества.'}
    option=min(options,key=lambda r:int(r['rank']))
    data['_reforge']={'save_id':ctx['save_id'],'hero_id':ctx['hero'][0],
        'session_id':ctx['session_id'],'slot':slot,'item_id':item['item_id'],
        'expected_modifier':item.get('modifier_id') or '',
        'modifier_id':option['modifier_id'],'rank':int(option['rank'])}
    data['slot']=slot
    return None

async def reserve_tx(conn, channel_id, username, action_id, data):
    r=data['_reforge']
    await conn.execute("INSERT INTO bannerlord_reforge_rights(channel_id,action_id,save_id,hero_id,username,slot,item_id,modifier_id,rank,state) VALUES (?,?,?,?,?,?,?,?,?,'pending')",
        (channel_id,action_id,r['save_id'],r['hero_id'],username,r['slot'],r['item_id'],r['modifier_id'],r['rank']))

async def settle_tx(conn, channel_id, action_id, success):
    await conn.execute("UPDATE bannerlord_reforge_rights SET state=? WHERE channel_id=? AND action_id=? AND state IN ('pending','active')",('active' if success else 'failed',channel_id,action_id))

async def rights_tx(conn, channel_id, save_id):
    rows=await (await conn.execute("SELECT hero_id,username,slot,item_id,modifier_id,rank FROM bannerlord_reforge_rights WHERE channel_id=? AND save_id=? AND state='active' ORDER BY rank",(channel_id,save_id))).fetchall()
    return [dict(zip(('hero_id','username','slot','item_id','modifier_id','rank'),r)) for r in rows]
