# Testing Playbook — Bannerlord Module

**Создан:** 2026-05-28
**Audience:** ты сам когда сядешь тестить + друг-программист
**Companion docs:** `BLT_AUDIT_2026-05-28.md` (что есть/что нет)

---

## 🎯 Цель документа

Step-by-step руководство как verify что новые sprints (SIEGE / DIPLO / SHOP /
FIEF / CARAVAN / HERITAGE) РЕАЛЬНО работают в живой кампании Bannerlord.
Каждый шаг имеет:
- **Действие** — что физически делать
- **Expected** — что должно произойти
- **Log check** — какие строки искать в `Logs/Mods/BannerlordLink.{TS}.log`
- **🐛 Common bug** — частые failure modes + fix hints

---

## 🛠 Setup checklist (один раз перед сессией)

### 1. Backend running

```bash
cd Расширение/backend
python main.py
```

Должен видеть:
```
✅ Migrations complete
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

Если ❌ M55/M56/M57/M58 migration failed — это **STOP**, fix migration first.

### 2. Smoke test backend baseline

```bash
cd Расширение/backend
python tests/bannerlord_smoke.py --host http://localhost:8000
```

Должен видеть: `RESULTS: 12 passed, 0 failed`. Если что-то ❌ — endpoint не
зарегистрирован или crash'нится на baseline. **STOP**, проверить routes.

### 3. Verbose logging enabled

Mod default = ON начиная с AUDIT-2 commit. Проверь в log header:
```
[VERBOSE] verbose logging = ON (детальные logs включены)
```

Если OFF — создай файл:
`Documents\Mount and Blade II Bannerlord\Configs\bannerlordlink_verbose.flag` (пустой)
Или удали `bannerlordlink_verbose_OFF.flag` если есть.

### 4. Bannerlord launch + mod loaded

Bannerlord → Mods → Shedoy23.BannerlordLink должен быть в списке + checked.
Запуск с **существующей save** или **fresh "Start New Game"**.

При launch в логе смотри:
```
v0.X.Y OnSubModuleLoad
[VERBOSE] verbose logging = ON
HarmonyPatch applied: NameMarkerPatch (если успешно)
MainCampaignBehavior registered
HeroIdentityBehavior registered (persistent username dict)
ClanUpgradesBehavior registered (daily clan upgrades tick)
WorkshopProfitSyncBehavior registered (daily profit → backend payout)
FiefTributeSyncBehavior registered (daily fief tribute → backend payout)
CaravanTrackerBehavior registered (caravan profit + destroyed event)
```

Если какой behavior НЕТ — он не зарегистрировался → его OnDailyTick не сработает →
**🐛 BUG: соответствующий sync не работает**.

### 5. Extension UI open

В Twitch chat → Extensions → твоё extension (или dev URL). Должны видеть:
- 🐪 Мои караваны (`bnr-caravans-slot`)
- 💀 Уничтоженные караваны (`bnr-caravan-rescue-slot` — только если есть destroyed)
- 🏭 Мои мастерские (`bnr-workshops-slot`)
- 👑 Мои владения (`bnr-fiefs-slot`)
- ⚱ Наследие (`bnr-inheritance-slot` — только если был death + inheritance)
- ⚔ Приказы моей партии (`bnr-party-orders-slot`)
- 🏛 Политика (`bnr-diplo-slot`)
- ⛓ В плену (`bnr-ransom-slot`)

Если **БЛОК НЕ ПОЯВЛЯЕТСЯ** — либо нет endpoint response, либо JS crash. Open
DevTools (F12), check Console для errors типа `loadBannerlordCaravans failed`.

---

## 📋 Phase 1 — BLT-DIRECT (high confidence working)

### TEST-1.1: Adopt a hero
**Действие:** в Twitch chat type `!adopt`
**Expected:** mod создаёт wanderer hero с name `[BLink] @твой_username`
**Log check:**
```
grep "AdoptHeroHandler" log.txt
grep "[BLink]" log.txt
```
Должен видеть `[adopt] @USERNAME → hero {StringId} created`
**🐛 Common:** mod не получает chat events → check IRC connection / EventSub auth

### TEST-1.2: Heal hero
**Действие:** Extension UI → купить "Лечение"
**Expected:** hero HP restores к MaxHitPoints, чат показывает confirmation
**Log check (mod):** `grep "HealHeroHandler"` или `grep "@USERNAME.*heal"`
**Log check (backend):** `grep "hero.heal\|player.heal" backend.log`
**🐛 Common:** action enqueued но не выполнено → mod offline / ActionPoller stopped

### TEST-1.3: Give gold
**Действие:** UI → "Дать 5000 динаров" (или preset)
**Expected:** Hero.Gold в-game увеличивается на presets amount
**Log check:** `grep "give_gold\|player.give_item" log`
**🐛 Common:** Wrong amount — check `GIVE_GOLD_PRESETS` mapping в routes/bannerlord.py

### TEST-1.4: Upgrade equipment (gear_tier)
**Действие:** UI → "Улучшить gear до T2" → confirm
**Expected:** Hero gets new equipment from T2 culture preset
**Log check (mod):** `grep "UpgradeGearHandler" log`
**Log check:** `gear_tier_changed` event in mod log
**🐛 Common:** insufficient Hero.Gold → action refused (мod side checks)

### TEST-1.5: Summon в Mission
**Действие:** Start any battle. Extension UI → "Призвать @username"
**Expected:** Adopted hero appears как ally в battle, near player
**Log check:** `grep "SummonHero\|player.spawn" log`
**🐛 Common:** Hero мёртв / wandering → can't summon

---

## 📋 Phase 2 — BLT-INSPIRED (medium confidence)

### TEST-2.1: Join tournament queue
**Действие:** UI → "Join tournament" + ставка
**Expected:** queue entry created, при tournament start hero participates
**Log check:** `grep "TournamentQueueBehavior\|join_tournament" log`
**🐛 Common:** Hero already in queue → duplicate refused

### TEST-2.2: Detachment in battle
**Действие:** В live battle: UI → "Detach hero" → "Hold position"
**Expected:** Adopted hero выходит из formation, stops на текущей позиции (sniper-mode)
**Log check:** `grep "HeroDetachmentBehavior\|DET" log`
Особенно `[DET V] reissue @username` — verbose mode шлёт каждые N ticks
**🐛 Common:** Solo formation не создаётся → reflection failed (engine API mismatch)

### TEST-2.3: CharacterEffect (FX powers)
**Действие:** UI → купить "Heal burst" / "Berserker charge" / "Poison DoT"
**Expected:** Visual fx + buff applied к adopted hero на mission duration
**Log check:** `grep "power.activate\|ActiveBuffState\|PowerVisualFx" log`
**🐛 Common:** Buff не visible → check `PowersMissionBehavior` registered, DamageHookPatch active

### TEST-2.4: Bulk clan upgrades
**Действие:** UI → Clan upgrades modal → quantity=5 → "Buy 5x"
**Expected:** Атомарная purchase 5 апгрейдов за один TX (Hero.Gold deducted)
**Log check:** `grep "BNR-BULK" backend.log`
**🐛 Common:** Один из апгрейдов не найден → весь TX rollback (correct behaviour)

### TEST-2.5: Party order SIEGE
**Setup:** твой viewer должен быть clan leader с MobileParty.
**Действие:** UI → "Назначить приказ" → SIEGE → target "Lycaron"
**Expected:** Party AI получает SetMoveBesiegeSettlement → starts marching toward Lycaron
**Log check (mod):**
```
grep "party_order ENTRY" log
grep "party_order.*SIEGE" log
grep "party_order EXIT-OK" log
```
**🐛 Common:** "Settlement not found" → fuzzy-name fail. Try `town_E1` instead of `Lycaron`

---

## 📋 Phase 3 — PLATFORM-NATIVE (lower confidence)

### TEST-3.1: Family proposal (FAM)
**Setup:** 2 виewers с alive взрослыми детьми разного пола.
**Действие:** Viewer A → UI → "Propose marriage to @B"
**Expected:** Backend INSERT'ит proposal, Viewer B видит pending в UI
**Log check (backend):** `grep "FAM-PROPOSE" log`
Viewer B respond → activate_marriage mod action → engine SetSpouse
**🐛 Common:** Child not adult yet → proposal refused

### TEST-3.2: Vassal sub-clan
**Setup:** Viewer is clan leader с взрослым heir.
**Действие:** UI → "Создать вассала" → choose heir + name
**Expected:** Mod creates new Clan via reflection (Hero.Clan setter), backend backfill
**Log check (mod):**
```
grep "CreateVassalClan ENTRY" log
grep "CreateVassalClan EXIT" log
grep "vassal_created" backend.log
```
**🐛 Common:** Reflection field name changed across 1.3.x patches → check `_clan` field

### TEST-3.3: SHOP — Workshop purchase
**Действие:** UI → "Купить мастерскую" → type "Smithy" + town "Pravend"
**Expected:** Mod calls `ChangeOwnerOfWorkshopAction.ApplyByBankruptcy` → ownership transfers
**Log check (mod):**
```
grep "shop-buy ENTRY" log
grep "shop-buy.*@username" log
```
**Verify in-game:** Open Pravend menu → Workshops → одна из них owned by `[BLink] @username`
**🐛 Common:** "No available slot" → all workshops в town already [BLink]-owned (try another town)

### TEST-3.4: SHOP — Daily profit sync
**Действие:** После TEST-3.3 → wait 1 in-game day (or speed up game time)
**Expected:** WorkshopProfitSyncBehavior diff'ит `Workshop.Capital`, пушит event
**Log check (mod):** `grep "shop-sync\|workshop_profit_sync" log`
**Log check (backend):** `grep "SHOP-SYNC" backend.log`
Viewer's crustic balance должна вырасти на (net_dinars / 100).
**🐛 Common:** Capital не растёт → workshop economy issue (low prosperity town?)

### TEST-3.5: FIEF tribute
**Setup:** Viewer-hero owns at least one town/castle/village (as clan leader)
**Действие:** Wait 1 in-game day
**Expected:** FiefTributeSyncBehavior diff'ит Town.Gold или Village.Hearth, push event
**Log check (mod):** `grep "fief-sync" log`
**Log check (backend):** `grep "FIEF-SYNC" backend.log`
**Verify UI:** `bnr-fiefs-slot` показывает row с накопленным dinars + crustic estimate
**🐛 Common:** Owner clan changed → row owner_username updates via UPSERT

### TEST-3.6: FIEF boost
**Действие:** UI fief row → "⚡ Boost"
**Expected:** boost_until = now + 7 days, next sync применяет ×1.5 multiplier
**Log check (backend):** `grep "FIEF-BOOST" backend.log`
**🐛 Common:** Already active boost → refuse

### TEST-3.7: CARAVAN — Create
**Действие:** UI → "Купить караван" → home "Pravend"
**Expected:** Mod calls `CaravanPartyComponent.CreateCaravanParty` → caravan party появляется на map
**Log check (mod):**
```
grep "caravan-buy ENTRY" log
grep "caravan-buy.*@username" log
grep "caravan_created" log
```
**🐛 Common:** Hero.Gold не хватает engine cost (~15K) → CreateCaravanParty crashes

### TEST-3.8: CARAVAN — Profit sync
**Действие:** Wait 1 in-game day after TEST-3.7
**Expected:** CaravanTrackerBehavior diffs PartyTradeGold, pushes event
**Log check:** `grep "caravan-sync\|caravan_profit_sync" log`
**🐛 Common:** Caravan только что создан, ещё не торговал → PartyTradeGold не вырос

### TEST-3.9: CARAVAN — Destroyed event
**Action:** Force caravan death — поезжай на caravan player party, attack and destroy
**Expected:** `MobilePartyDestroyed` event → mod push `hero.caravan_destroyed`
**Backend response:** mark caravan status='destroyed', rescue pool opens
**Log check:** `grep "caravan-destroyed\|CARAVAN-DESTROYED" log`
**Verify UI:** `bnr-caravan-rescue-slot` shows destroyed entry с progress bar 0/2500
**🐛 Common:** Wrong owner detection — destroyed by AI, not [BLink] → ignored

### TEST-3.10: HERITAGE flow
**Setup:** Viewer accumulated workshops/caravans/fiefs. Viewer has adult heir.
**Действие:** Kill viewer's hero (admin command или battle defeat)
**Expected:**
1. backend `_on_player_died` collects active assets
2. Logs entries в `bannerlord_inheritance_log`
3. Enqueues `hero.activate_heir` с inherited_workshops + inherited_caravans
4. Mod's `ActivateHeirHandler` renames heir → `[BLink] @parent_username`
5. Transfer engine ownership workshops/caravans к heir hero
**Log check (backend):**
```
grep "HEIR-ACTIVATE" log
grep "HERITAGE.*assets passed" log
```
**Log check (mod):**
```
grep "heir.activate ENTRY.*workshops_inherited" log
grep "heir.heritage.*reclaimed" log
```
**Verify UI:** `bnr-inheritance-slot` displays inheritance log entries
**🐛 Common:** Heir already activated (другая смерть бы before) → refuse

---

## 🔍 Log Discovery — где что

**Mod log file:**
```
%USERPROFILE%\Documents\Mount and Blade II Bannerlord\Logs\Mods\BannerlordLink.{TIMESTAMP}.log
```

**Backend log:** stdout / stderr `python main.py`. Можно `python main.py > backend.log 2>&1`

**Useful greps:**
| Sprint | Mod log grep | Backend log grep |
|--------|--------------|------------------|
| SIEGE   | `party_order` | `SIEGE-SET\|SIEGE-RELEASE` |
| DIPLO   | `diplo-` | `DIPLO-POLICY\|DIPLO-PEACE\|DIPLO-RANSOM` |
| SHOP    | `shop-buy\|shop-sell\|shop-sync` | `SHOP-BUY\|SHOP-SELL\|SHOP-SYNC` |
| FIEF    | `fief-sync` | `FIEF-SYNC\|FIEF-BOOST` |
| CARAVAN | `caravan-buy\|caravan-sell\|caravan-sync\|caravan-destroyed` | `CARAVAN-` |
| HERITAGE| `heir.activate\|heir.heritage` | `HEIR-ACTIVATE\|HERITAGE` |

---

## 🚨 Critical Failure Patterns

### "Mod не loadится"
1. Check Bannerlord launcher → Mods → mod checked + load order
2. Check log file existence in `Logs/Mods/`
3. If нет log file = mod crash on init OR DLL missing → rebuild `dotnet build`

### "Action enqueued но не выполнен"
Pattern: backend logs `ENQUEUE action_id=...` но mod НЕ logs `ENTRY`
Causes:
- Mod offline (BackendClient.PollActionsAsync stopped)
- Module token не валиден (401 от backend's GET actions endpoint)
- Action type не registered в `ActionRegistry.RegisterDefaults()`

### "Event пуш не доходит до backend"
Pattern: mod logs `event TYPE → ACK` но backend нет log line
Causes:
- Backend down / другой host
- Network firewall
- channel_id mismatch (mod's config.ChannelId != backend's expectation)

### "UI пустой / endpoint 500"
Pattern: extension panel пустой, DevTools показывает 500 на GET
Causes:
- DB migration не применилась → `python tests/bannerlord_smoke.py` подскажет
- Route handler crash на нестандартных data → check `backend.log` traceback

---

## 🎬 Quick smoke session (10 минут)

Если у тебя 10 минут free и хочешь minimum confidence что nothing badly broken:

```bash
# 1. Backend smoke
cd Расширение/backend && python tests/bannerlord_smoke.py
# Expected: 12 passed, 0 failed

# 2. Mock event flow (no game required)
set MODULE_TOKEN=YOUR_TOKEN
python tests/mock_mod_events.py --scenario all --channel 1 --username smoke_viewer
# Expected: каждый event → "ACK" / "ok"

# 3. Frontend visual check
open https://shedstream.org/dashboard или dev URL
# Verify все panels рендерятся, no JS errors в Console
```

Если все три ✅ — Backend + frontend baseline OK, можно идти в live кампанию.
Если хоть один ❌ — фикси сначала baseline.

---

**Last updated:** 2026-05-28
