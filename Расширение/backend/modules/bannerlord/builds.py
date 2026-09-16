"""Thin authorization of save-owned specializations and weapon powers."""
import time
from .equipment_shop import context, refusal as equipment_refusal

ACTION_TYPES = frozenset({'hero.set_specialization', 'hero.select_weapon_power', 'hero.claim_starter'})


def refusal(reason):
    messages = {
        'build_not_ready': 'Настройки героя ещё синхронизируются с игрой',
        'build_unavailable': 'Сейчас нельзя менять сборку героя',
        'hero_prisoner': 'Герой в плену — изменить сборку можно после освобождения',
        'in_battle': 'Менять сборку можно только между боями',
        'invalid_specialization': 'Такой специализации нет',
        'weapon_unavailable': 'Нужное оружие отсутствует в надетом комплекте',
        'invalid_starter': 'Этот стартовый комплект недоступен',
        'starter_claimed': 'Стартовый комплект уже получен',
        'power_not_selected': 'Выбери эту оружейную способность перед боем',
        'not_in_battle': 'Способности доступны только в бою',
    }
    if reason in messages:
        return {'success': False, 'reason': reason, 'message': messages[reason]}
    return equipment_refusal(reason)


def manage_reason(ctx):
    if ctx['reason']:
        return ctx['reason']
    build = ctx['build']
    if build.get('version') != 1:
        return 'build_not_ready'
    if build.get('is_prisoner'):
        return 'hero_prisoner'
    if build.get('in_battle'):
        return 'in_battle'
    if not build.get('can_manage'):
        return 'build_unavailable'
    return None


async def validate_tx(conn, channel_id, username, action_type, data):
    """Same transaction as cash register; never trust viewer costs/identity/effects."""
    ctx = await context(conn, channel_id, username)
    build = ctx['build']
    if action_type == 'power.activate':
        # Legacy channels remain usable; once a new equipment session exists,
        # missing build data must fail closed rather than unlock old class powers.
        if not ctx['session_id']:
            data.pop('_weapon_build', None)
            return None
        reason = ctx['reason']
        if reason:
            return refusal(reason)
        if build.get('version') != 1:
            return refusal('build_not_ready')
        if not build.get('in_battle'):
            return refusal('not_in_battle')
        power_key = data.get('power_key')
        if power_key != 'heal_burst':
            option = next((x for x in build.get('power_options', [])
                           if x.get('weapon_type') == build.get('selected_weapon_type')
                           and x.get('power_key') == power_key), None)
            if power_key != build.get('selected_power') or not option:
                return refusal('power_not_selected')
            if not option.get('available'):
                return refusal('weapon_unavailable')
            from ._adapter import check_cooldown
            remaining = max(check_cooldown(channel_id, username, 'weapon_power'),
                            float(build.get('weapon_power_cooldown_until') or 0) - time.time())
            if remaining > 0:
                return {'success': False, 'reason': 'cooldown', 'message': 'Оружейная способность на перезарядке',
                        'cooldown_remaining_s': round(remaining, 1)}
        payload = {'power_key': power_key, 'price': data['price']}
        if power_key != 'heal_burst':
            payload.update(weapon_type=build['selected_weapon_type'], _weapon_build=True)
    else:
        reason = manage_reason(ctx)
        if reason:
            return refusal(reason)
        payload = {'price': 0}
        if action_type == 'hero.set_specialization':
            key = data.get('specialization')
            if not any(x.get('id') == key for x in build.get('specializations', [])):
                return refusal('invalid_specialization')
            payload['specialization'] = key
        elif action_type == 'hero.select_weapon_power':
            key = data.get('weapon_type')
            if not any(x.get('weapon_type') == key and x.get('available') for x in build.get('power_options', [])):
                return refusal('weapon_unavailable')
            payload['weapon_type'] = key
        else:
            if build.get('starter_claimed'):
                return refusal('starter_claimed')
            key = data.get('starter_kit')
            if not any(x.get('id') == key and x.get('available') for x in build.get('starter_kits', [])):
                return refusal('invalid_starter')
            payload['starter_kit'] = key
    payload.update(save_id=ctx['save_id'], equipment_session_id=ctx['session_id'], hero_id=ctx['hero'][0])
    client_id = data.get('client_action_id')
    data.clear()
    data.update(payload)
    if client_id:
        data['client_action_id'] = client_id
    return None
