"""Engine-owned equipment catalog and inventory; backend authorizes, mod spends gold."""
import json

ACTION_TYPES = frozenset({"hero.buy_equipment", "hero.equip_owned", "hero.unequip_owned"})
TIER_LEVELS = {1: 1, 2: 10, 3: 15, 4: 25, 5: 30, 6: 35}


def refusal(reason):
    messages = {
        "inventory_not_ready": "Инвентарь ещё синхронизируется с игрой",
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
    }
    return {"success": False, "reason": reason, "message": messages[reason]}


async def context(conn, channel_id, username):
    cur = await conn.execute(
        "SELECT hero_id,level,gold,is_alive FROM bannerlord_heroes WHERE channel_id=? AND username=?",
        (channel_id, username))
    hero = await cur.fetchone()
    cur = await conn.execute("SELECT current_save_id FROM bannerlord_channel_state WHERE channel_id=?", (channel_id,))
    state = await cur.fetchone()
    save_id = state[0] if state else None
    cur = await conn.execute("SELECT session_id FROM bannerlord_equipment_sessions WHERE channel_id=?", (channel_id,))
    session = await cur.fetchone()
    session_id = session[0] if session else None
    cur = await conn.execute(
        "SELECT items_json,build_json FROM bannerlord_inventory_snapshots WHERE channel_id=? AND username=? AND save_id=? AND hero_id=? AND session_id=?",
        (channel_id, username, save_id, hero[0] if hero else "", session_id))
    snapshot = await cur.fetchone()
    cur = await conn.execute(
        "SELECT 1 FROM module_actions WHERE channel_id=? AND module_id='bannerlord' "
        "AND type IN ('hero.buy_equipment','hero.equip_owned','hero.unequip_owned',"
        "'hero.set_specialization','hero.select_weapon_power','hero.claim_starter','power.activate') "
        "AND status IN ('queued','dispatched') AND json_extract(data,'$.initiated_by')=? LIMIT 1",
        (channel_id, username))
    pending = bool(await cur.fetchone())
    reason = "no_hero" if not hero else "hero_dead" if not hero[3] else "inventory_not_ready" if not snapshot else "pending" if pending else None
    return {"hero": hero, "save_id": save_id, "session_id": session_id, "inventory": json.loads(snapshot[0]) if snapshot else [],
            "build": json.loads(snapshot[1]) if snapshot else {},
            "ready": bool(snapshot), "pending": pending, "reason": reason}


async def catalog(conn, channel_id):
    cur = await conn.execute(
        "SELECT payload FROM module_catalogs WHERE channel_id=? AND module_id='bannerlord' AND catalog_type='equipment' ORDER BY entry_id",
        (channel_id,))
    return [json.loads(row[0]) for row in await cur.fetchall()]


def buy_reason(item, ctx):
    if ctx["reason"]:
        return ctx["reason"]
    if ctx["hero"][1] < item["required_level"]:
        return "level_locked"
    if ctx["hero"][2] < item["price_gold"]:
        return "insufficient_gold"
    return None


async def validate_tx(conn, channel_id, username, action_type, data):
    """Must run under the SAME BEGIN IMMEDIATE as outbox insertion."""
    ctx = await context(conn, channel_id, username)
    if ctx["reason"]:
        return refusal(ctx["reason"])
    payload = {"price": 0, "save_id": ctx["save_id"], "equipment_session_id": ctx["session_id"], "hero_id": ctx["hero"][0]}
    if action_type == "hero.buy_equipment":
        item = next((x for x in await catalog(conn, channel_id) if x["item_id"] == data.get("item_id")), None)
        if item is None:
            return refusal("item_not_found")
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
        payload.update(owned_id=owned["owned_id"], slot=data["slot"])
    else:
        if not any(x.get("slot") and x["slot"] == data.get("slot") for x in ctx["inventory"]):
            return refusal("empty_slot")
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
            "INSERT INTO bannerlord_inventory_snapshots(channel_id,username,save_id,session_id,hero_id,inventory_seq,items_json,build_json) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(channel_id,username) DO UPDATE SET save_id=excluded.save_id,session_id=excluded.session_id,hero_id=excluded.hero_id,"
            "inventory_seq=excluded.inventory_seq,items_json=excluded.items_json,build_json=excluded.build_json "
            "WHERE excluded.inventory_seq>bannerlord_inventory_snapshots.inventory_seq OR excluded.save_id!=bannerlord_inventory_snapshots.save_id "
            "OR excluded.hero_id!=bannerlord_inventory_snapshots.hero_id OR excluded.session_id!=bannerlord_inventory_snapshots.session_id",
            (channel_id, username, data["save_id"], data["equipment_session_id"], data["hero_id"], seq,
             json.dumps(items, ensure_ascii=False), json.dumps(data.get('build') if isinstance(data.get('build'), dict) else {}, ensure_ascii=False)))
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
