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

# 2026-08-19: цепочка if/else заменена реестром (frontend/viewer-registry.js).
# Проверка «останови всех, кроме активной» переехала из строк исходника в
# ПОВЕДЕНЧЕСКИЙ тест tests/test_game_registry.js — строковая проверка зеленела
# бы и тогда, когда до этих строк не доходит управление. Здесь остаётся только
# проводка: ядро делегирует в реестр, каждая игра объявляет себя сама.
# 2026-08-20: конец функции ищем по её закрывающей скобке, а не по соседнему
# заголовку. Прежний маркер «// ===== Daily rewards…» уехал вместе с
# Bannerlord-кодом в его файл, и проверка молча начала читать ВЕСЬ остаток
# ядра — то есть проверяла не то, что написано в её же названии.
switcher = viewer.split(
    "function switchIntegrationModule(activeModule) {", 1)[1].split(
        "\n}", 1)[0]

check("ShedLink.switchGame" in switcher,
      "ядро переключает игры через реестр, а не через свой if/else")
check("bannerlord" not in switcher and "rimworld" not in switcher,
      "ядро больше не знает имён игр внутри переключателя")

shedcolony = (FRONTEND / "viewer-shedcolony.js").read_text(encoding="utf-8")
for name, src, root in (
    ("Bannerlord", bannerlord, "bannerlord-content"),
    ("RimWorld", rimworld, "rimworld-content"),
    ("ShedColony", shedcolony, "shedcolony-content"),
):
    check("ShedLink.registerGame(" in src and root in src,
          "%s объявляет себя реестру и называет свой корневой блок" % name)
# 2026-08-19: список модулей больше не перечисляется руками. Раньше регулярка
# знала только viewer.js / -bannerlord / -rimworld, поэтому ShedColony (добавлен
# 25.06) в проверку не попадал: его версия могла разъехаться между оболочками, а
# тест оставался зелёным. Каждая следующая игра унаследовала бы ту же слепоту.
# Теперь имена берутся из самих оболочек и с диска.
def module_versions(shell):
    return {
        name: version
        for name, version in re.findall(
            r'(viewer(?:-[\w-]+)?\.js)\?v=([0-9]{12})', shell)
    }


ext_versions = module_versions(html)
mobile_versions = module_versions(mobile)
on_disk = {f.name for f in FRONTEND.glob("viewer*.js")}

check(bool(ext_versions) and set(ext_versions) == set(mobile_versions),
      "обе оболочки грузят один и тот же набор viewer-модулей "
      "(ext=%s mobile=%s)" % (sorted(ext_versions), sorted(mobile_versions)))
check(ext_versions == mobile_versions,
      "версия каждого viewer-модуля одинакова в extension и mobile "
      "(расходятся: %s)" % sorted(
          n for n in set(ext_versions) & set(mobile_versions)
          if ext_versions[n] != mobile_versions[n]))
check(len(set(ext_versions.values()) | set(mobile_versions.values())) == 1,
      "cache-bust всех viewer-модулей — одна метка")
check(on_disk == set(ext_versions),
      "каждый viewer*.js с диска подключён в оболочках "
      "(не подключены: %s)" % sorted(on_disk - set(ext_versions)))
check("const unavailable = !heroReady;" in bannerlord
      and "bnrCanUseActivePowers()" in bannerlord,
      "платные active powers выключены, пока герой не на поле боя")

print("=" * 70)
print("PASSED: %d   FAILED: %d" % (passed, failed))
print("ALL GREEN — неактивный RimWorld молчит."
      if not failed else "КРАСНО — module lifecycle снова протекает.")
sys.exit(1 if failed else 0)
