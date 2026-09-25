"""Engine-owned equipment catalog and inventory; backend authorizes, mod spends gold."""
import json

ACTION_TYPES = frozenset({"hero.buy_equipment", "hero.equip_owned", "hero.unequip_owned", "hero.discard_owned"})
TIER_LEVELS = {1: 1, 2: 10, 3: 15, 4: 25, 5: 30, 6: 35}


def refusal(reason):
    messages = {
        "inventory_not_ready": "Игра ещё не передала инвентарь этого героя",
        "inventory_state_unknown": "Обнови мод и загрузи сохранение: доступ к багажу ещё не подтверждён",
        "hero_prisoner": "Герой в плену — багаж отряда недоступен, смена снаряжения запрещена",
        "no_party_inventory": "У героя сейчас нет доступного багажа отряда",
        "no_hero": "Сначала создай героя",
        "hero_dead": "Герой погиб",
        "pending": "Предыдущее действие с экипировкой ещё выполняется",
        "item_not_found": "Предмета нет в текущем каталоге игры",
        "level_locked": "Уровень героя слишком низкий для этого тира",
        "insufficient_gold": "Недостаточно динаров героя",
        "not_owned": "Предмет не принадлежит этому герою",
        "invalid_slot": "Предмет нельзя надеть в этот слот",
        "empty_slot": "В этом слоте ничего нет",
        "offline": "Игра сейчас не на связи",
        "in_mission": "Купить и надеть можно после выхода из боя или сцены",
        "purchase_slot_required": "Выбери слот и подтверди покупку с надеванием",
        "equipment_changed": "Снаряжение изменилось. Обнови магазин и подтверди замену заново",
        "equipment_price_changed": "Цена замены изменилась. Обнови магазин",
        "inventory_state_changed": "У героя появился или исчез багаж. Обнови магазин",
        "gold_limit_reached": "Продажа превысит предел динаров героя",
        "stash_full": "Личный сундук героя полон (10 мест): надень или выкинь что-нибудь",
    }
    return {"success": False, "reason": reason, "message": messages[reason]}


async def context(conn, channel_id, username, *, require_party=False, for_shop=False):
    cur = await conn.execute(
        "SELECT hero_id,level,gold,is_alive,is_prisoner FROM bannerlord_heroes WHERE channel_id=? AND username=?",
        (channel_id, username))
    hero = await cur.fetchone()
    cur = await conn.execute("SELECT current_save_id FROM bannerlord_channel_state WHERE channel_id=?", (channel_id,))
    state = await cur.fetchone()
    save_id = state[0] if state else None
    cur = await conn.execute("SELECT session_id FROM bannerlord_equipment_sessions WHERE channel_id=?", (channel_id,))
    session = await cur.fetchone()
    session_id = session[0] if session else None
    cur = await conn.execute(
        "SELECT items_json,build_json,inventory_state_json FROM bannerlord_inventory_snapshots WHERE channel_id=? AND username=? AND save_id=? AND hero_id=? AND session_id=?",
        (channel_id, username, save_id, hero[0] if hero else "", session_id))
    snapshot = await cur.fetchone()
    cur = await conn.execute(
        "SELECT 1 FROM module_actions WHERE channel_id=? AND module_id='bannerlord' "
        "AND type IN ('hero.buy_equipment','hero.equip_owned','hero.unequip_owned','hero.discard_owned',"
        "'hero.set_specialization','hero.select_weapon_power','hero.claim_starter','power.activate') "
        "AND status IN ('queued','dispatched') AND json_extract(data,'$.initiated_by')=? LIMIT 1",
        (channel_id, username))
    pending = bool(await cur.fetchone())
    state = json.loads(snapshot[2]) if snapshot else {}
    party_reason = ('hero_prisoner' if hero and hero[4] else
                    state.get('party_reason') if state.get('party_reason') in ('hero_prisoner', 'no_party_inventory') else
                    None if state.get('party_available') is True and state.get('party_id') else
                    'inventory_state_unknown' if snapshot else 'inventory_not_ready')
    inventory = json.loads(snapshot[0]) if snapshot else []
    if party_reason:
        inventory = [item for item in inventory if item.get('source') != 'party']
    # 25.09 (владелец): без своего отряда вещи держит личный сундук героя.
    # Это отдельный признак от мода — «багажа отряда нет» остаётся правдой.
    # Места в сундуке считаем у всех: с 25.09 покупки и снятое всегда идут в
    # сундук, даже при своём отряде (его инвентарь игра распродаёт в городах).
    slots = None
    if type(state.get('stash_count')) is int:
        count, cap = state.get('stash_count'), state.get('stash_capacity')
        slots = {"count": count if count >= 0 else 0,
                 "capacity": cap if type(cap) is int and cap > 0 else 10}
    stash = None
    if party_reason == 'no_party_inventory' and state.get('stash_available') is True:
        count, cap = state.get('stash_count'), state.get('stash_capacity')
        stash = {"count": count if type(count) is int and count >= 0 else 0,
                 "capacity": cap if type(cap) is int and cap > 0 else 10}
    manage_reason = None if stash else party_reason
    reason = "no_hero" if not hero else "hero_dead" if not hero[3] else "inventory_not_ready" if not snapshot else (manage_reason if require_party else None) or ("pending" if pending else None)
    direct_purchase = party_reason == 'no_party_inventory' and not stash and state.get('buy_equip_available') is True
    if for_shop:
        shop_reason = ('in_mission' if state.get('in_mission') is not False else None) if direct_purchase else manage_reason
        reason = ("no_hero" if not hero else "hero_dead" if not hero[3] else
                  "inventory_not_ready" if not snapshot else shop_reason or ("pending" if pending else None))
    build = json.loads(snapshot[1]) if snapshot else {}
    return {"hero": hero, "save_id": save_id, "session_id": session_id, "inventory": inventory,
            "party_inventory": {"available": manage_reason is None, "reason": manage_reason,
                                "message": refusal(manage_reason)['message'] if manage_reason else '',
                                "party_id": state.get('party_id') if not party_reason else None,
                                "party_name": state.get('party_name') if not party_reason else
                                f"Личный сундук героя ({stash['count']}/{stash['capacity']})" if stash else None},
            "stash": stash,
            "stash_slots": slots or stash,
            "build": build if isinstance(build, dict) else {},
            "legacy_build": bool(snapshot) and build is None,
            "direct_purchase": direct_purchase,
            "ready": bool(snapshot), "pending": pending, "reason": reason}


async def catalog(conn, channel_id):
    cur = await conn.execute(
        "SELECT payload FROM module_catalogs WHERE channel_id=? AND module_id='bannerlord' AND catalog_type='equipment' ORDER BY entry_id",
        (channel_id,))
    return [json.loads(row[0]) for row in await cur.fetchall()]


def stash_full(ctx):
    slots = ctx.get("stash_slots")
    return bool(slots) and slots["count"] >= slots["capacity"]


def buy_reason(item, ctx, *, net_price=None):
    if ctx["reason"]:
        return ctx["reason"]
    if net_price is None and stash_full(ctx):
        return "stash_full"
    if ctx["hero"][1] < item["required_level"]:
        return "level_locked"
    if ctx["hero"][2] < (item["price_gold"] if net_price is None else max(0, net_price)):
        return "insufficient_gold"
    if net_price is not None and ctx["hero"][2] - net_price > 2147483647:
        return "gold_limit_reached"
    return None


def purchase_options(item, ctx):
    options = []
    for slot in item.get('slots', []):
        old = next((x for x in ctx['inventory'] if x.get('slot') == slot), None)
        trade = old.get('trade_in_gold') if old else 0
        known = type(trade) is int and 0 <= trade <= 2147483647 and not (old and old.get('unavailable'))
        net = item['price_gold'] - trade if known else item['price_gold']
        reason = buy_reason(item, ctx, net_price=net) or (None if known else 'inventory_state_unknown')
        options.append(dict(slot=slot, replace_owned_id=old['owned_id'] if old else '',
                            replace_item_id=old['item_id'] if old else '',
                            replace_modifier_id=(old.get('modifier_id') or '') if old else '',
                            replaced_name=old.get('name', old.get('item_id')) if old else None,
                            trade_in_gold=trade if known else 0, net_price_gold=net,
                            can_buy=reason is None, reason=reason,
                            message=refusal(reason)['message'] if reason else ''))
    return options


async def validate_tx(conn, channel_id, username, action_type, data):
    """Must run under the SAME BEGIN IMMEDIATE as outbox insertion."""
    buying = action_type == 'hero.buy_equipment'
    ctx = await context(conn, channel_id, username, require_party=True, for_shop=buying)
    if ctx["reason"]:
        return refusal(ctx["reason"])
    payload = {"price": 0, "save_id": ctx["save_id"], "equipment_session_id": ctx["session_id"], "hero_id": ctx["hero"][0]}
    if action_type == "hero.buy_equipment":
        item = next((x for x in await catalog(conn, channel_id) if x["item_id"] == data.get("item_id")), None)
        if item is None:
            return refusal("item_not_found")
        if ctx['direct_purchase']:
            if data.get('equip_now') is not True:
                return refusal('purchase_slot_required')
            option = next((x for x in purchase_options(item, ctx) if x['slot'] == data.get('slot')), None)
            if option is None:
                return refusal('invalid_slot')
            if data.get('replace_owned_id') != option['replace_owned_id']:
                return refusal('equipment_changed')
            if any(data.get(key) != option[key] for key in ('replace_item_id', 'replace_modifier_id')):
                return refusal('equipment_changed')
            if type(data.get('expected_price_gold')) is not int or data['expected_price_gold'] != item['price_gold']:
                return refusal('equipment_price_changed')
            if type(data.get('expected_trade_in_gold')) is not int or data['expected_trade_in_gold'] != option['trade_in_gold']:
                return refusal('equipment_price_changed')
            if option['reason']:
                return refusal(option['reason'])
            old = next((x for x in ctx['inventory'] if x.get('slot') == option['slot']), None)
            payload.update(equip_now=True, slot=option['slot'], trade_in_gold=option['trade_in_gold'],
                           expected_item_id=old['item_id'] if old else '',
                           expected_modifier_id=(old.get('modifier_id') or '') if old else '')
        else:
            if data.get('equip_now') is True:
                return refusal('inventory_state_changed')
            reason = buy_reason(item, ctx)
            if reason:
                return refusal(reason)
        payload.update({k: item[k] for k in ("item_id", "price_gold", "required_level", "tier")})
    elif action_type == "hero.equip_owned":
        owned = next((x for x in ctx["inventory"] if x["owned_id"] == data.get("owned_id")), None)
        if not owned:
            return refusal("not_owned")
        if data.get("slot") not in owned.get("slots", []):
            return refusal("invalid_slot")
        payload.update(owned_id=owned["owned_id"], slot=data["slot"],
                       source=owned.get("source"), item_id=owned.get("item_id"),
                       modifier_id=owned.get("modifier_id"))
    elif action_type == "hero.discard_owned":
        owned = next((x for x in ctx["inventory"] if x["owned_id"] == data.get("owned_id")), None)
        if not owned:
            return refusal("not_owned")
        payload.update(owned_id=owned["owned_id"], source=owned.get("source"),
                       item_id=owned.get("item_id"), modifier_id=owned.get("modifier_id"))
    else:
        if not any(x.get("slot") and x["slot"] == data.get("slot") for x in ctx["inventory"]):
            return refusal("empty_slot")
        if stash_full(ctx):
            return refusal("stash_full")
        payload["slot"] = data["slot"]
    client_id = data.get("client_action_id")
    data.clear()  # No viewer-supplied costs, targets, ids or modifiers reach the mod.
    data.update(payload)
    if client_id:
        data["client_action_id"] = client_id
    return None


async def store_inventory(db, channel_id, env):
    data = env.data
    username = str(data.get("username") or "").lower()
    items = data.get("items")
    seq = data.get("inventory_seq")
    if type(seq) is not int or seq < 1:
        return
    if not username or not isinstance(items, list) or not data.get("save_id") or not data.get("hero_id"):
        return
    if any(not isinstance(x, dict) or not x.get("owned_id") or not x.get("item_id") for x in items):
        return
    if len({x["owned_id"] for x in items}) != len(items):
        return
    async with db._connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        cur = await conn.execute(
            "SELECT 1 FROM bannerlord_channel_state s JOIN bannerlord_heroes h ON h.channel_id=s.channel_id "
            "JOIN bannerlord_equipment_sessions e ON e.channel_id=s.channel_id "
            "WHERE s.channel_id=? AND s.current_save_id=? AND h.username=? AND h.hero_id=? AND e.session_id=?",
            (channel_id, data["save_id"], username, data["hero_id"], data.get("equipment_session_id")))
        if not await cur.fetchone():
            await conn.rollback()
            return
        await conn.execute(
            "INSERT INTO bannerlord_inventory_snapshots(channel_id,username,save_id,session_id,hero_id,inventory_seq,items_json,build_json,inventory_state_json) VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(channel_id,username) DO UPDATE SET save_id=excluded.save_id,session_id=excluded.session_id,hero_id=excluded.hero_id,"
            "inventory_seq=excluded.inventory_seq,items_json=excluded.items_json,build_json=excluded.build_json,inventory_state_json=excluded.inventory_state_json "
            "WHERE excluded.inventory_seq>bannerlord_inventory_snapshots.inventory_seq OR excluded.save_id!=bannerlord_inventory_snapshots.save_id "
            "OR excluded.hero_id!=bannerlord_inventory_snapshots.hero_id OR excluded.session_id!=bannerlord_inventory_snapshots.session_id",
            (channel_id, username, data["save_id"], data["equipment_session_id"], data["hero_id"], seq,
             json.dumps(items, ensure_ascii=False), json.dumps(data.get('build') if 'build' in data and (data['build'] is None or isinstance(data['build'], dict)) else {}, ensure_ascii=False),
             json.dumps(data.get('inventory_state') if isinstance(data.get('inventory_state'), dict) else {}, ensure_ascii=False)))
        await conn.commit()


async def store_catalog(db, channel_id, env):
    """Replace catalog atomically only for current save; tier gates are server-owned."""
    entries = env.data.get("entries")
    if not isinstance(entries, list) or not env.data.get("save_id"):
        return
    normalized = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        item_id = entry.get("item_id")
        tier, gold = entry.get("tier"), entry.get("price_gold")
        if not isinstance(item_id, str) or not item_id or type(tier) is not int or tier not in TIER_LEVELS or type(gold) is not int or gold < 1:
            continue
        normalized.append({**entry, "id": item_id, "item_id": item_id, "required_level": TIER_LEVELS[tier]})
    async with db._connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        cur = await conn.execute("SELECT 1 FROM bannerlord_channel_state s JOIN bannerlord_equipment_sessions e ON e.channel_id=s.channel_id WHERE s.channel_id=? AND s.current_save_id=? AND e.session_id=?", (channel_id, env.data["save_id"], env.data.get("equipment_session_id")))
        if not await cur.fetchone():
            await conn.rollback()
            return
        await conn.execute("DELETE FROM module_catalogs WHERE channel_id=? AND module_id='bannerlord' AND catalog_type='equipment'", (channel_id,))
        for item in normalized:
            await conn.execute(
                "INSERT OR REPLACE INTO module_catalogs(channel_id,module_id,catalog_type,entry_id,payload) VALUES(?,'bannerlord','equipment',?,?)",
                (channel_id, item["id"], json.dumps(item, ensure_ascii=False)))
        await conn.commit()
