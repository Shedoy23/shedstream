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
check("лимит пяти детей enforced модом и отражён frontend",
      "DEFAULT_MAX_ALIVE_CHILDREN = 5" in mod_baby and
      "aliveChildren.length < 5" in front)

if fails:
    print("\nПРОВАЛЕНО: " + "; ".join(fails))
    raise SystemExit(1)
print("\nВСЁ ЗЕЛЁНОЕ")
