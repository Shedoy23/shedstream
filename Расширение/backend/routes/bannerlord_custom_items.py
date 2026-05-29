"""
Sprint 5.29 / BLT-parity #6 MVP — Custom items (Smithing trophies).

Текущая итерация — backend-only trophy collection. Viewer покупает
`hero.smith_item` action (100K💰 Hero.Gold + 500 крустиков), backend
генерирует random custom item с уникальным именем и rarity, кладёт в
inventory. UI показывает collection.

Future: real Bannerlord ItemObject (HeroEquipment integration), auction,
item transfer между viewers.

Endpoints:
  GET  /api/bannerlord/custom-items — мой inventory
  POST /api/bannerlord/custom-items/smith — call smith action

Smith action также проходит через стандартный buy_action flow
(_PURCHASABLE_ACTIONS + ACTION_PRICES_DEFAULT), там списываются крустики.
Hero.Gold deduction делается через manifest action_type "hero.smith_item"
который mod может игнорировать (no in-game effect yet), а backend сам
генерирует trophy на event ack.

В MVP — мы делаем smith INLINE в этом endpoint'е (не через mod), сразу
вставляем в DB. Mod опционально пушит cosmetic event.
"""
from __future__ import annotations

import logging
import random
from typing import Dict, List, Optional

from fastapi import APIRouter, Request

from dependencies import get_db, require_jwt_user

router = APIRouter()
log = logging.getLogger("rimlink.bannerlord.custom_items")


# ── Rarity weights (BLT-style, биased к common, лестница вверх) ──────────────
RARITY_WEIGHTS = [
    ("common",    60),
    ("uncommon",  25),
    ("rare",      10),
    ("epic",       4),
    ("legendary",  1),
]
RARITY_COLORS = {
    "common":    "#adadb8",   # grey
    "uncommon":  "#22c55e",   # green
    "rare":      "#3b82f6",   # blue
    "epic":      "#a855f7",   # purple
    "legendary": "#fbbf24",   # gold
}
RARITY_ICONS = {
    "common":    "⚪",
    "uncommon":  "🟢",
    "rare":      "🔵",
    "epic":      "🟣",
    "legendary": "🟡",
}

# ── Name generators ──────────────────────────────────────────────────────────
WEAPON_SUBTYPES = ["Меч", "Топор", "Копьё", "Молот", "Лук", "Арбалет", "Кинжал", "Глефа"]
ARMOR_SUBTYPES  = ["Шлем", "Кираса", "Поножи", "Перчатки", "Плащ"]
HORSE_SUBTYPES  = ["Конь", "Верблюд", "Жеребец"]

ADJECTIVES_COMMON = ["Старый", "Простой", "Затупленный", "Поношенный"]
ADJECTIVES_UNCOMMON = ["Боевой", "Сталный", "Прочный", "Калёный"]
ADJECTIVES_RARE = ["Сверкающий", "Ледяной", "Огненный", "Бурный", "Серебряный"]
ADJECTIVES_EPIC = ["Кровожадный", "Тёмный", "Пылающий", "Громовой", "Воскрешённый"]
ADJECTIVES_LEGENDARY = [
    "Драконоборец", "Зимоликий", "Кровавая Луна", "Сумеречный",
    "Несокрушимый", "Безумный Жнец",
]
ADJ_BY_RARITY = {
    "common":    ADJECTIVES_COMMON,
    "uncommon":  ADJECTIVES_UNCOMMON,
    "rare":      ADJECTIVES_RARE,
    "epic":      ADJECTIVES_EPIC,
    "legendary": ADJECTIVES_LEGENDARY,
}

# Sprint 5.32 (BLT-parity M14) — раньше тут был SMITH_GOLD_COST = 100_000,
# но он нигде не списывался (handler НЕ дёргал mod.hero.spend_gold). Был
# чисто декоративной константой. Удалён в M14 cleanup. Если в будущем
# понадобится Hero.Gold cost — добавить отдельный action в module_actions
# с amount, mod execute'нет GiveGoldAction.ApplyBetweenCharacters(hero, null, cost).
#
# Cost в крустиках — server-enforced через ACTION_PRICES_DEFAULT в bannerlord.py
# ("hero.smith_item": 500), handled в общем buy_action flow.


def _roll_rarity() -> str:
    """Weighted random pick."""
    total = sum(w for _, w in RARITY_WEIGHTS)
    r = random.randint(1, total)
    cum = 0
    for rarity, w in RARITY_WEIGHTS:
        cum += w
        if r <= cum:
            return rarity
    return "common"


def _roll_stats(base_type: str, rarity: str) -> dict:
    """Sprint 5.33 (BLT-parity ITEM) — roll rarity-based stat bonuses.

    Weapon  → damage_bonus  (outgoing)
    Armor   → armor_bonus + weight_factor (incoming + speed)
    Horse   → speed_factor + armor_bonus (mount)

    Min/max ranges per rarity escalate. Non-applicable fields = 0 / 1.0.
    """
    # (dmg_min, dmg_max, armor_min, armor_max, factor_swing)
    ranges = {
        "common":    (1, 3,   1, 2,   0.03),   # ±3% factor
        "uncommon":  (3, 6,   2, 4,   0.06),
        "rare":      (6, 10,  4, 7,   0.10),
        "epic":      (10, 15, 7, 11,  0.13),
        "legendary": (15, 25, 11, 18, 0.18),
    }
    r = ranges.get(rarity, ranges["common"])
    dmg_min, dmg_max, arm_min, arm_max, fct = r

    damage_bonus = 0
    armor_bonus = 0
    weight_factor = 1.0
    speed_factor = 1.0

    if base_type == "weapon":
        damage_bonus = random.randint(dmg_min, dmg_max)
    elif base_type == "armor":
        armor_bonus = random.randint(arm_min, arm_max)
        # Лучшая броня — обычно тяжелее. Но Lordly-pattern может дать +armor +speed.
        # Roll: 30% chance weight_factor < 1.0 (lighter even with armor)
        if random.random() < 0.3:
            weight_factor = round(1.0 - random.uniform(0, fct), 3)
        else:
            weight_factor = round(1.0 + random.uniform(0, fct * 0.5), 3)
    else:  # horse
        speed_factor = round(1.0 + random.uniform(0, fct), 3)
        armor_bonus = random.randint(arm_min // 2, arm_max // 2)  # lighter armor

    return {
        "damage_bonus":  damage_bonus,
        "armor_bonus":   armor_bonus,
        "weight_factor": weight_factor,
        "speed_factor":  speed_factor,
    }


def _generate_item(base_type: str) -> Dict:
    """Roll random custom item — name + rarity + tier + Sprint 5.33 stats."""
    rarity = _roll_rarity()
    tier = {"common": 1, "uncommon": 2, "rare": 3, "epic": 4, "legendary": 5}.get(rarity, 1)
    if base_type == "weapon":
        subtype = random.choice(WEAPON_SUBTYPES)
    elif base_type == "armor":
        subtype = random.choice(ARMOR_SUBTYPES)
    else:
        subtype = random.choice(HORSE_SUBTYPES)
    adj = random.choice(ADJ_BY_RARITY[rarity])
    name = f"{adj} {subtype}"
    stats = _roll_stats(base_type, rarity)
    return {
        "base_type":    base_type,
        "base_subtype": subtype,
        "custom_name":  name,
        "rarity":       rarity,
        "tier":         tier,
        "icon":         RARITY_ICONS[rarity],
        **stats,   # damage_bonus / armor_bonus / weight_factor / speed_factor
    }


def generate_prize_item() -> Dict:
    """Tournament prize — random type, rarity biased вверх (награда не должна
    быть мусором). Common апгрейдится до uncommon+. Phase B."""
    base_type = random.choice(["weapon", "armor", "horse"])
    item = _generate_item(base_type)
    if item["rarity"] == "common":
        prize_rarity = random.choices(
            ["uncommon", "rare", "epic", "legendary"],
            weights=[50, 30, 15, 5])[0]
        tier = {"uncommon": 2, "rare": 3, "epic": 4, "legendary": 5}[prize_rarity]
        item["rarity"] = prize_rarity
        item["tier"] = tier
        item["icon"] = RARITY_ICONS[prize_rarity]
        adj = random.choice(ADJ_BY_RARITY[prize_rarity])
        item["custom_name"] = f"{adj} {item['base_subtype']}"
        item.update(_roll_stats(base_type, prize_rarity))
    return item


async def insert_custom_item(conn, channel_id: int, username: str,
                             item: Dict, source: str) -> int:
    """Insert a generated item into the unified inventory (persists rolled
    stats + source). Returns new id (0 on fail). Caller commits. Phase B."""
    cur = await conn.execute(
        "INSERT INTO bannerlord_custom_items "
        "(channel_id, owner_username, base_type, base_subtype, custom_name, "
        " rarity, tier, icon, damage_bonus, armor_bonus, weight_factor, "
        " speed_factor, source, claimed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0) RETURNING id",
        (channel_id, username, item["base_type"], item["base_subtype"],
         item["custom_name"], item["rarity"], item["tier"], item["icon"],
         item.get("damage_bonus", 0), item.get("armor_bonus", 0),
         item.get("weight_factor", 1.0), item.get("speed_factor", 1.0), source))
    row = await cur.fetchone()
    return row[0] if row else 0


# ── API ──────────────────────────────────────────────────────────────────────

@router.get("/api/bannerlord/custom-items")
async def viewer_custom_items(request: Request):
    """Inventory custom items viewer'а — newest first."""
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "auth required"}
    username, channel_id = auth

    async with get_db()._connect() as conn:
        cur = await conn.execute(
            "SELECT id, base_type, base_subtype, custom_name, rarity, tier, "
            "       icon, created_at, "
            "       COALESCE(damage_bonus, 0), COALESCE(armor_bonus, 0), "
            "       COALESCE(weight_factor, 1.0), COALESCE(speed_factor, 1.0), "
            "       COALESCE(source, 'forge'), COALESCE(claimed, 0) "
            "FROM bannerlord_custom_items "
            "WHERE channel_id=? AND owner_username=? "
            "ORDER BY id DESC LIMIT 100",
            (channel_id, username))
        rows = await cur.fetchall()

    items = []
    for r in rows:
        items.append({
            "id":            r[0],
            "base_type":     r[1],
            "base_subtype":  r[2],
            "custom_name":   r[3],
            "rarity":        r[4],
            "tier":          r[5],
            "icon":          r[6],
            "color":         RARITY_COLORS.get(r[4], "#adadb8"),
            "created_at":    r[7],
            # Sprint 5.33 (BLT-parity ITEM) — rolled stats
            "damage_bonus":  r[8],
            "armor_bonus":   r[9],
            "weight_factor": r[10],
            "speed_factor":  r[11],
            # Phase B — inventory unification
            "source":        r[12],   # 'forge' | 'tournament'
            "claimed":       bool(r[13]),
        })
    return {
        "success":   True,
        "items":     items,
        "total":     len(items),
        "max_slots": 50,
    }


@router.post("/api/bannerlord/custom-items/smith")
async def viewer_smith_item(request: Request):
    """Forge custom item. Type chosen by viewer: weapon|armor|horse.

    Crustic price enforced via standard buy_action flow (вызывайте оттуда).
    Hero.Gold list deduction — TODO когда mod integration будет готова.
    Текущая итерация: pure backend trophy generation.
    """
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "auth required"}
    username, channel_id = auth

    try:
        body = await request.json()
    except Exception:
        body = {}
    base_type = (body.get("base_type") or "").strip().lower()
    if base_type not in ("weapon", "armor", "horse"):
        return {
            "success": False,
            "message": "base_type должен быть weapon / armor / horse",
        }

    # Slot limit check
    async with get_db()._connect() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) FROM bannerlord_custom_items "
            "WHERE channel_id=? AND owner_username=?",
            (channel_id, username))
        cnt_row = await cur.fetchone()
        current_count = int(cnt_row[0]) if cnt_row else 0
        if current_count >= 50:
            return {
                "success": False,
                "message": "Инвентарь полон (50 max). Дискарди что-то.",
            }

        # Generate + insert (Phase B — persists rolled stats + source='forge')
        item = _generate_item(base_type)
        item_id = await insert_custom_item(conn, channel_id, username, item, "forge")
        await conn.commit()

    log.info("[bannerlord SMITH] ch=%s user=%s base=%s rarity=%s name='%s'",
             channel_id, username, base_type, item["rarity"], item["custom_name"])
    return {
        "success":  True,
        "message":  f"{item['icon']} Создан: {item['custom_name']} ({item['rarity']})",
        "item":     {**item, "id": item_id, "color": RARITY_COLORS[item["rarity"]]},
    }


@router.post("/api/bannerlord/custom-items/discard")
async def viewer_discard_item(request: Request):
    """Discard custom item (free)."""
    auth = require_jwt_user(request)
    if not auth:
        return {"success": False, "message": "auth required"}
    username, channel_id = auth

    try:
        body = await request.json()
    except Exception:
        body = {}
    item_id = int(body.get("item_id") or 0)
    if not item_id:
        return {"success": False, "message": "item_id required"}

    async with get_db()._connect() as conn:
        cur = await conn.execute(
            "DELETE FROM bannerlord_custom_items "
            "WHERE id=? AND channel_id=? AND owner_username=?",
            (item_id, channel_id, username))
        await conn.commit()
        if cur.rowcount == 0:
            return {"success": False, "message": "Item не найден / не твой"}

    log.info("[bannerlord DISCARD] ch=%s user=%s item_id=%s",
             channel_id, username, item_id)
    return {"success": True, "message": "Item discarded"}
