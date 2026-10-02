"""Personal progression snapshot; game costs are metadata, never backend formulas."""
import copy
import json

ACTION_TYPES = frozenset({'hero.add_skill', 'hero.add_focus', 'hero.add_attribute'})
_CONTEXT = ('save_id', 'equipment_session_id', 'hero_id')


def reason_text(reason):
    messages = {
        'progression_not_ready': 'Игра ещё не передала возможности прокачки этого героя.',
        'progression_changed': 'Герой или игровая сессия изменились. Обнови панель.',
        'progression_quote_changed': 'Цена или значение изменились. Обнови панель и подтверди заново.',
        'progression_option_not_found': 'Игра не предлагает этот вариант прокачки.',
        'progression_unavailable': 'Сейчас эта прокачка недоступна в игре.',
        'platform_price_changed': 'Цена в крустиках изменилась. Обнови панель.',
        'pending': 'Предыдущая прокачка ещё выполняется.',
    }
    if not reason:
        return None
    from .refusals import describe
    return messages.get(reason) or describe(reason)


def refusal(reason):
    return dict(success=False, reason=reason, message=reason_text(reason))


def normalize(value):
    """Malformed/missing full snapshots revoke readiness instead of retaining old offers."""
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1:
        return {}
    from .content_catalogs import _text
    if type(value.get('random_xp_available')) is not bool:
        return {}
    for collection, value_key, options_key in [('skills','focus','focus_options'), ('attributes','value','options')]:
        entries=value.get(collection)
        if not isinstance(entries,list) or len(entries)>2000:
            return {}
        seen=set()
        for entry in entries:
            if not isinstance(entry,dict) or not _text(entry.get('id'),256,required=True) or entry['id'] in seen:
                return {}
            seen.add(entry['id'])
            if type(entry.get(value_key)) is not int or entry[value_key]<0:
                return {}
            if collection=='skills' and type(entry.get('xp_available')) is not bool:
                return {}
            options=entry.get(options_key)
            if not isinstance(options,list) or len(options)>1000:
                return {}
            amounts=set()
            for option in options:
                if (not isinstance(option,dict) or type(option.get('amount')) is not int or option['amount']<=0
                        or option['amount']>2147483647 or option['amount'] in amounts
                        or type(option.get('cost_gold')) is not int or not 0<=option['cost_gold']<=2147483647
                        or type(option.get('available')) is not bool):
                    return {}
                amounts.add(option['amount'])
                if option.get('reason') is not None and not _text(option['reason'],512):
                    return {}
            if entry.get('xp_reason') is not None and not _text(entry['xp_reason'],512):
                return {}
    if value.get('random_xp_reason') is not None and not _text(value['random_xp_reason'],512):
        return {}
    return value if len(json.dumps(value).encode('utf-8')) <= 4*1024*1024 else {}


async def context(conn,channel_id,username):
    row=await (await conn.execute(
        'SELECT s.current_save_id,e.session_id,h.hero_id,i.progression_json FROM bannerlord_heroes h '
        'JOIN bannerlord_channel_state s ON s.channel_id=h.channel_id '
        'JOIN bannerlord_equipment_sessions e ON e.channel_id=h.channel_id '
        'LEFT JOIN bannerlord_inventory_snapshots i ON i.channel_id=h.channel_id AND i.username=h.username '
        'AND i.save_id=s.current_save_id AND i.session_id=e.session_id AND i.hero_id=h.hero_id '
        'WHERE h.channel_id=? AND h.username=?',(channel_id,username))).fetchone()
    identity=dict(zip(_CONTEXT,row[:3])) if row else None
    value=normalize(json.loads(row[3])) if row and row[3] else {}
    pending=bool(await (await conn.execute(
        "SELECT 1 FROM module_actions WHERE channel_id=? AND module_id='bannerlord' "
        "AND type IN ('hero.add_skill','hero.add_focus','hero.add_attribute') AND status IN ('queued','dispatched') "
        "AND json_extract(data,'$.initiated_by')=? LIMIT 1",(channel_id,username))).fetchone())
    return dict(context=identity,progression=value,ready=bool(value),pending=pending,
                reason='progression_not_ready' if not value else 'pending' if pending else None)


def present(value):
    value=copy.deepcopy(value)
    for skill in value.get('skills',[]):
        skill['xp_reason_text']=reason_text(skill.get('xp_reason'))
        for option in skill.get('focus_options',[]):
            option['reason_text']=reason_text(option.get('reason'))
    for attr in value.get('attributes',[]):
        for option in attr.get('options',[]):
            option['reason_text']=reason_text(option.get('reason'))
    value['random_xp_reason_text']=reason_text(value.get('random_xp_reason'))
    return value


async def validate(conn,channel_id,username,action_type,data,*,prepared=False,price=None):
    ctx=await context(conn,channel_id,username)
    if ctx['reason']:
        return refusal(ctx['reason'])
    # 02.10: панель 0.0.5 (замороженная на CDN Twitch до следующего релиза) шлёт
    # {skill_key,amount} / {attribute_key,amount} / {price} без контекста и котировок.
    # Отказывать ей — значит закрыть зрителям три кнопки до релиза. Без контекста
    # котировку берёт сервер из последнего снимка игры; мод всё равно сверяет её с
    # игрой перед списанием, так что убрать поле нарочно ничего не даёт.
    legacy = data.get('_legacy_progression') is True if prepared else 'progression_context' not in data
    if legacy and not prepared:
        data['progression_context']=dict(ctx['context'])
    supplied=data.get('progression_context')
    if not isinstance(supplied,dict) or any(supplied.get(k)!=ctx['context'][k] for k in _CONTEXT):
        return refusal('progression_changed')
    is_xp=action_type=='hero.add_skill'
    attr=action_type=='hero.add_attribute'
    key_name='attribute_key' if attr else 'skill_key'
    key=data.get(key_name,'')
    if not isinstance(key,str):
        return refusal('progression_option_not_found')
    entries=ctx['progression']['attributes' if attr else 'skills']
    entry=next((x for x in entries if x['id']==key),None)
    if entry is None and legacy and key:
        # 0.0.5 шлёт атрибуты из своего списка с большой буквы ('Vigor'), игра называет
        # их 'vigor'. Старой панели — совпадение без регистра, только если оно однозначно;
        # дальше идёт настоящий id игры. Новая панель сравнивает точно (моды различают регистр).
        folded=[x for x in entries if isinstance(x.get('id'),str) and x['id'].casefold()==key.casefold()]
        if len(folded)==1:
            entry=folded[0]; key=entry['id']
    payload={key_name:key}
    if is_xp:
        if not key:
            available=ctx['progression']['random_xp_available']; why=ctx['progression'].get('random_xp_reason')
        elif entry:
            available=entry['xp_available']; why=entry.get('xp_reason')
        else:
            return refusal('progression_option_not_found')
        if not available:
            return refusal(why or 'progression_unavailable')
        if legacy:
            # Старая панель не знает итоговой цены со скидками: показанная цена = базовая.
            data['expected_platform_price']=price if prepared else data.get('price')
        expected=data.get('expected_platform_price')
        if type(expected) is not int or expected<0 or (prepared and expected!=price):
            return refusal('platform_price_changed')
        from routes.bannerlord import ADD_SKILL_XP_PRESETS
        base = data.get('_progression_base_price') if prepared else data.get('price')
        if type(base) is not int or base not in ADD_SKILL_XP_PRESETS:
            return refusal('platform_price_changed')
        payload.update(xp=ADD_SKILL_XP_PRESETS[base],price=data['price'])
        if not prepared:
            payload['_progression_base_price']=base
            payload['expected_platform_price']=expected
    else:
        amount=data.get('amount',1)
        option=next((x for x in entry['options' if attr else 'focus_options'] if x['amount']==amount),None) if entry and type(amount) is int else None
        if not option:
            return refusal('progression_option_not_found')
        current=entry['value' if attr else 'focus']
        if legacy:
            data['expected_cost_gold']=option['cost_gold']
            data['expected_value']=current
        if (type(data.get('expected_cost_gold')) is not int or data['expected_cost_gold']!=option['cost_gold']
                or type(data.get('expected_value')) is not int or data['expected_value']!=current):
            return refusal('progression_quote_changed')
        if not option['available']:
            return refusal(option.get('reason') or 'progression_unavailable')
        payload.update(amount=amount,price=0,expected_cost_gold=option['cost_gold'],expected_value=current)
    payload.update(ctx['context'])
    if not prepared:
        payload['progression_context']=dict(ctx['context'])
        if legacy:
            payload['_legacy_progression']=True
    else:
        for field in ('reward_boost','_perk_label'):
            if field in data:
                payload[field]=data[field]
    client_id=data.get('client_action_id')
    data.clear(); data.update(payload)
    if client_id:
        data['client_action_id']=client_id
    return None
