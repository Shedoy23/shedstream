# -*- coding: utf-8 -*-
"""Игровой frontend не опрашивает неактивный модуль.

Стрим 03.08: Bannerlord-панель сделала тысячи запросов к RimWorld, потому что
RimWorld polling стартовал при парсе JS, а auth-init безусловно грузил pawn,
shop и events. Тест держит lifecycle-контракт на уровне загрузочных точек.

Запуск: python tests/test_frontend_module_lifecycle.py
"""
from pathlib import Path
import re
import sys


FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
viewer = (FRONTEND / "viewer.js").read_text(encoding="utf-8")
rimworld = (FRONTEND / "viewer-rimworld.js").read_text(encoding="utf-8")
html = (FRONTEND / "extension.html").read_text(encoding="utf-8")
mobile = (FRONTEND / "mobile.html").read_text(encoding="utf-8")
bannerlord = (FRONTEND / "viewer-bannerlord.js").read_text(encoding="utf-8")

passed = 0
failed = 0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print("  OK  ", message)
    else:
        failed += 1
        print("  FAIL", message)


def between(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


auth_init = between(
    viewer,
    "function updateUIAfterAuth() {",
    "// Sprint 5.31 #45b — обновить бейдж роли",
)
rimworld_calls = (
    "loadColonists()",
    "loadMyPawn()",
    "loadShopCatalog()",
    "loadRimworldEvents()",
    "checkRimworldStatus()",
)

check(not any(call in auth_init for call in rimworld_calls),
      "core auth-init не грузит RimWorld без active_module")
check("window._startRimworldPolling = function" in rimworld,
      "RimWorld имеет явный start lifecycle")
check("window._stopRimworldPolling = function" in rimworld,
      "RimWorld имеет явный stop lifecycle")
check("safeInterval(checkRimworldStatus, 30000)" in rimworld,
      "status polling запускается lifecycle-функцией")
check("if (_activeIntegrationModule !== 'rimworld') return;" in rimworld,
      "локальный UI tick тоже gated по активному модулю")

switcher = between(
    viewer,
    "function switchIntegrationModule(activeModule) {",
    "// ===== Daily rewards / Heirs / Family",
)
check("window._startRimworldPolling" in switcher,
      "switcher запускает RimWorld только в его ветке")
check(switcher.count("window._stopRimworldPolling") >= 3,
      "switcher останавливает RimWorld во всех остальных ветках")
def module_versions(shell):
    return {
        name: version
        for name, version in re.findall(
            r'(viewer(?:-bannerlord|-rimworld)?\.js)\?v=([0-9]{12})', shell)
    }


ext_versions = module_versions(html)
mobile_versions = module_versions(mobile)
check(set(ext_versions) == {"viewer.js", "viewer-bannerlord.js", "viewer-rimworld.js"}
      and ext_versions == mobile_versions
      and len(set(ext_versions.values())) == 1,
      "cache-bust трёх модулей синхронен в extension и mobile")
check("const unavailable = !heroReady;" in bannerlord
      and "bnrCanUseActivePowers()" in bannerlord,
      "платные active powers выключены, пока герой не на поле боя")

print("=" * 70)
print("PASSED: %d   FAILED: %d" % (passed, failed))
print("ALL GREEN — неактивный RimWorld молчит."
      if not failed else "КРАСНО — module lifecycle снова протекает.")
sys.exit(1 if failed else 0)
