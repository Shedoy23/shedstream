"""Cross-layer guards for the Bannerlord limits/prices mirrored for UI only."""
from __future__ import annotations

import re
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "Расширение" / "backend" / "routes" / "bannerlord.py"
ADAPTER = ROOT / "Расширение" / "backend" / "modules" / "bannerlord" / "_adapter.py"
FRONT = ROOT / "Расширение" / "frontend" / "viewer-bannerlord.js"
MOD_RECRUIT = ROOT / "BannerlordLink" / "src" / "Actions" / "RecruitTroopsHandler.cs"
MOD_BABY = ROOT / "BannerlordLink" / "src" / "Actions" / "MakeBabyHandler.cs"

fails: list[str] = []


def check(name: str, ok: bool) -> None:
    print(("  OK   " if ok else "  FAIL ") + name)
    if not ok:
        fails.append(name)


def numbers(block: str) -> list[int]:
    code = "\n".join(line.split("//", 1)[0] for line in block.splitlines())
    return [int(x.replace("_", "")) for x in re.findall(r"\b\d[\d_]*\b", code)]


backend = BACKEND.read_text(encoding="utf-8")
adapter = ADAPTER.read_text(encoding="utf-8")
front = FRONT.read_text(encoding="utf-8")
mod_recruit = MOD_RECRUIT.read_text(encoding="utf-8")
mod_baby = MOD_BABY.read_text(encoding="utf-8")

expected = [5000, 10000, 20000, 30000, 50000, 80000]
backend_tiers = re.search(r"RECRUIT_TIER_COSTS\s*=\s*\[([^]]+)\]", backend, re.S)
front_tiers = re.search(r"RETINUE_TIER_DINARS\s*=\s*\[([^]]+)\]", front, re.S)
mod_tiers = re.search(r"TIER_COSTS\s*=\s*\{([^}]+)\}", mod_recruit, re.S)
check("стоимость свиты совпадает frontend/backend/mod",
      bool(backend_tiers and front_tiers and mod_tiers) and
      numbers(backend_tiers.group(1)) == expected and
      numbers(front_tiers.group(1)) == expected and
      numbers(mod_tiers.group(1)) == expected)
check("elite multiplier совпадает frontend/backend/mod",
      "ELITE_COST_MULTIPLIER = 3" in backend and
      "RETINUE_ELITE_MULT = 3" in front and
      "ELITE_COST_MULTIPLIER = 3f" in mod_recruit)
check("лимит пяти вассалов enforced backend",
      "cnt_row[0] >= 5" in (ROOT / "Расширение" / "backend" / "routes" /
                             "bannerlord_vassals.py").read_text(encoding="utf-8") and
      "vassals.length < 5" in front)
check("bulk limit 10 enforced backend и отражён frontend",
      "len(upgrade_ids) > 10" in backend and "count <= 10" in front)
check("дипломатический cooldown 300 enforced backend и отражён frontend",
      bool(re.search(r'"kingdom\.propose_war"\s*:\s*300', adapter)) and
      bool(re.search(r'"kingdom\.propose_peace"\s*:\s*300', adapter)) and
      "const _DIPLO_CD = 300" in front)
check("лимит детей объявлен одинаково в backend, моде и фронте",
      "MAX_ALIVE_CHILDREN = 5" in backend and
      "DEFAULT_MAX_ALIVE_CHILDREN = 5" in mod_baby and
      "aliveChildren.length < 5" in front)

# ── Подменённый payload: предел ставит сервер ────────────────────────────────
# Прошлая версия этой проверки искала в исходнике мода строку
# "DEFAULT_MAX_ALIVE_CHILDREN = 5" и на этом успокаивалась. Она была зелёной,
# пока дыра была открыта: мод читает предел из data["max_alive_children"]
# (принимает 1..20), backend это поле не ставил, а data — тело запроса
# зрителя, которое доезжает до мода как есть. То есть текст константы в моде
# ничего не доказывал: наличие умолчания не мешает его переопределить.
# Поэтому здесь исполняется НАСТОЯЩАЯ _prepare_action с враждебным payload'ом.
def _spoofed_payload_is_overridden() -> bool:
    import asyncio
    import os

    backend_dir = str(ROOT / "Расширение" / "backend")
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    for var, val in (("TWITCH_OAUTH_TOKEN", "oauth:x"), ("TWITCH_CLIENT_ID", "x"),
                     ("TWITCH_CLIENT_SECRET", "x"), ("TWITCH_BOT_ID", "x"),
                     ("TWITCH_CHANNEL_NAME", "x")):
        os.environ.setdefault(var, val)

    import routes.bannerlord as bnr

    async def _clan(_channel_id, _username):
        return "ТестКлан"

    async def _gold(_channel_id, _username):
        return bnr.BABY_COST * 10

    orig_clan, orig_gold = bnr._fetch_hero_clan_name, bnr._fetch_hero_gold
    bnr._fetch_hero_clan_name, bnr._fetch_hero_gold = _clan, _gold
    try:
        hostile = {"max_alive_children": 20, "price": 0, "_user_role": "viewer"}
        refusal = asyncio.new_event_loop().run_until_complete(
            bnr._prepare_action("attacker", 123456, "hero.make_baby", hostile))
    finally:
        bnr._fetch_hero_clan_name, bnr._fetch_hero_gold = orig_clan, orig_gold

    if refusal is not None:
        print("     (действие отклонено целиком: %r)" % (refusal,))
        return False
    got = hostile.get("max_alive_children")
    if got != bnr.MAX_ALIVE_CHILDREN:
        print("     подменённый предел выжил: прислано 20, в очередь ушло %r "
              "(ожидалось %r)" % (got, bnr.MAX_ALIVE_CHILDREN))
        return False
    return True


check("подменённый max_alive_children перезаписывается сервером",
      _spoofed_payload_is_overridden())


# ── Ещё два поля, которые мод читал, а сервер не задавал (найдено 09.09) ──────
# Метод тот же: исполняем настоящую _prepare_action с враждебным телом.
# Искать текст в исходнике здесь бесполезно — обе дыры были именно в ОТСУТСТВИИ
# кода, а отсутствие строки грепом не отличить от «ещё не написали».
def _call_prepare(action_type: str, data: dict):
    """Вернуть (отказ|None, data после обработки)."""
    import asyncio
    import os

    backend_dir = str(ROOT / "Расширение" / "backend")
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    for var, val in (("TWITCH_OAUTH_TOKEN", "oauth:x"), ("TWITCH_CLIENT_ID", "x"),
                     ("TWITCH_CLIENT_SECRET", "x"), ("TWITCH_BOT_ID", "x"),
                     ("TWITCH_CHANNEL_NAME", "x")):
        os.environ.setdefault(var, val)
    import routes.bannerlord as bnr

    async def _clan(_c, _u):
        return "ТестКлан"

    async def _gold(_c, _u):
        return 10_000_000

    orig = bnr._fetch_hero_clan_name, bnr._fetch_hero_gold
    bnr._fetch_hero_clan_name, bnr._fetch_hero_gold = _clan, _gold
    try:
        refusal = asyncio.new_event_loop().run_until_complete(
            bnr._prepare_action("attacker", 123456, action_type, data))
    finally:
        bnr._fetch_hero_clan_name, bnr._fetch_hero_gold = orig
    return refusal, data


def _power_overrides_stripped() -> bool:
    """ActivatePowerHandler.cs:48-49 берёт duration_s/value из payload'а и
    отдаёт их в Activate() для десяти способностей. Бэкенд обязан их снять:
    силу и длительность назначает мод, а не покупатель."""
    hostile = {"power_key": "rage", "duration_s": 9999.0, "value": 999.0,
               "price": 0, "_user_role": "viewer"}
    refusal, data = _call_prepare("power.activate", hostile)
    if refusal is not None:
        print("     (power.activate отклонён целиком: %r)" % (refusal,))
        return False
    left = [k for k in ("duration_s", "value") if k in data]
    if left:
        print("     клиентские override'ы доехали до мода: %s"
              % ", ".join("%s=%r" % (k, data[k]) for k in left))
        return False
    return True


def _legacy_attribute_twin_refused() -> bool:
    """player.modify_attribute стоил 50 крустиков и не имел ветки вовсе:
    points шёл из тела, мод применял его без потолка. Рядом hero.add_attribute
    зажимает 1..10 и берёт 50 000 динаров ЗА ОЧКО."""
    hostile = {"attribute": "Vigor", "points": 1000, "price": 0,
               "_user_role": "viewer"}
    refusal, data = _call_prepare("player.modify_attribute", hostile)
    if refusal is None:
        print("     действие НЕ отклонено, points=%r ушёл к моду"
              % data.get("points"))
        return False
    return refusal.get("success") is False


check("power.activate: клиентские duration_s/value снимаются сервером",
      _power_overrides_stripped())
check("player.modify_attribute (легаси-двойник) отклоняется",
      _legacy_attribute_twin_refused())

if fails:
    print("\nПРОВАЛЕНО: " + "; ".join(fails))
    raise SystemExit(1)
print("\nВСЁ ЗЕЛЁНОЕ")
