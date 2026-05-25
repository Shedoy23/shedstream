# Bannerlord BLink Integration Audit

**Date:** 2026-05-25
**Scope:** Mod (C#) + Backend (FastAPI) + Frontend (Twitch extension JS)
**Mode:** Read-only audit + logging-only fixes. Major refactors tracked as tasks.

---

## TL;DR — самые опасные паттерны

| # | Что | Слой | Severity | Status |
|---|---|---|---|---|
| 1 | **«ACK success + silent refuse»** — viewer платит крустики, мод тихо отказывает, refund нет | Mod + Backend | **HIGH** | Task #21 (open) |
| 2 | **Viewer-supplied `price` принимается** для `world.trigger_event`, `player.heal`, `player.modify_attribute` | Backend | **HIGH** | Сегодня fix |
| 3 | **Frontend double-fire** — `_bannerlordBuyAction` без in-flight guard, rapid click = двойная оплата | Frontend | **HIGH** | Сегодня fix |
| 4 | **Hero.Gold double-spend** — две одновременные команды читают cached gold, обе validate, мод отказывает второй, refund нет | Backend | **HIGH** | Связано с #1 |
| 5 | **ClanUpgradesBehavior `_ownedByUser` без lock** — Task.Run пишет, model overrides читают | Mod | **HIGH** | Сегодня fix |
| 6 | **Сломанный HTML** — пропущенный `</button>` в random-equip | Frontend | MED | Сегодня fix |
| 7 | **Spam-prone actions без cooldown** (recruit/heal/equip/add_attr/add_focus) | Backend | MED | Tracked в #28 (per-user CD) |
| 8 | **Dispatched actions могут залипнуть** если мод упал между fetch и ACK | Backend | MED | Будущий sweeper |
| 9 | **6 manifest events без handler'а** в backend adapter (clan_left, kingdom_created, etc) → stale cache | Backend | MED | Сегодня fix |
| 10 | **Buff/cooldown ticker drift** — client-side decrement вместо `expires_at_ms` | Frontend | MED | Будущий fix |

---

## A. Mod audit findings

Всего проверено: 27 action handlers + 6 behaviors + 4 Harmony patches + 5 net/util files.

### A.1 Silent-fail (≈12 handlers поражены)

Pattern: `ExecuteAsync` сразу возвращает `(success, null)`, MainThreadDispatcher.Enqueue запускает Apply на main thread, Apply'у нужно много pre-checks (mission state, hero alive, has gold), любой fail просто `Log(...) + return`. Backend не знает что mod отказал, viewer заплатил крустики/динары.

Affected handlers с file:line:
- `SummonHeroHandler.cs:82-148` — 6 silent return paths
- `UpgradeGearHandler.cs:135-157` — 4 paths
- `EquipItemHandler.cs:76-127` — 5 paths
- `AddAttributeHandler.cs:60-128` — 5 paths
- `CreateClanHandler.cs:75-123` — 5 paths
- `CreatePartyHandler.cs:73-170` — 8 paths
- `LeaveClanHandler.cs:62-138` — 4 paths
- `MarryHandler.cs:127-130` — silent на «no candidates» (Sprint 5.29 partially logged)
- `JoinTournamentHandler.cs:55-83` — 4 paths
- `ActivatePowerHandler.cs:61-108` — 3 paths
- `HealHeroHandler.cs:29-36` — 2 paths
- `GiveGoldHandler.cs:43-47` — 2 paths

**Полный fix:** task #21 (refund-on-failed event).
**Сегодняшние логи:** добавить `REFUSE` prefix во все relevant log lines чтобы можно было `grep REFUSE` для триажа.

### A.2 Race conditions

| File:Line | Issue | Fix |
|---|---|---|
| `Behaviors/ClanUpgradesBehavior.cs:36-39` | `_ownedByUser`, `_effectsByUpgrade` plain Dictionary, mutated from Task.Run (background) + read from model overrides (any thread) → torn reads / Collection-modified | Atomic-swap pattern с lock — **сегодня fix** |
| `Behaviors/TournamentQueueBehavior.cs:50` `_queue` | Mutated from action handler (main via dispatcher) + HeroKilledEvent listener (campaign thread) | Wrap в lock |
| `Behaviors/TournamentMissionBehavior.cs:45` `_roundsWon` | Plain Dictionary mutated от Harmony postfix + main thread | ConcurrentDictionary |
| `Patches/IsSideDepletedPatch.cs:41`, `SummonHeroHandler.cs:579,605-616` | Iterate `Mission.Current.Agents` без snapshot — engine может изменить mid-enumerate | Snapshot `.ToList()` |
| `Behaviors/KillRewardBehavior.cs:401` | `Mission?.MissionResult` — `Mission` может flip к null между calls | Cache `var m = Mission;` once |

### A.3 Lost economy (gold deduct vs side-effects order)

| File:Line | Bug |
|---|---|
| `CreatePartyHandler.cs:159→209` | Gold deducted AFTER party spawn; если spawn вернул "half-baked party" → 200K потеряно, broken party |
| `CreateClanHandler.cs:166` | Gold deducted AFTER `Clan.CreateClan` succeeded BUT banner/culture/HomeSettlement try-catches могут swallow ошибки → clan создан malformed, gold взят |
| `UpgradeGearHandler.cs:215` | Gold deducted AFTER equipment mods; если `EquipmentSync.PushAll` throws → gold lost, backend не знает о tier change |
| `MarryHandler.cs:141-142` | Spouse links set BEFORE party cleanup; если cleanup throws → marriage half-applied |
| `SummonHeroHandler.cs:208` | `originParty.AddToCounts(+1)` после `originalHeroParty.AddToCounts(-1)` — если +1 throws, hero потерян из original party |

### A.4 Logic gaps

- `KillRewardBehavior.cs:431` `IsPlayerSide` flag default false — participants без OnAgentBuild trigger считаются enemy. Если стример проиграл, эти viewers credited как winners.
- `TournamentQueueBehavior.cs:244-265` `StartingTournament = null` только в finally — если что-то between line 233-264 throws AFTER queue drain, StartingTournament stays non-null до следующего set
- `TournamentMissionBehavior.cs:230` `tb.Winner` — struct, no null-check; если Winner never set → NRE в OnTournamentEnd
- `AdoptHeroHandler.cs:117-128` Hero set Active before HeroDeveloper.ClearHero(); если Clear throws → broken hero в world + viewer думает adopt failed

### A.5 Logging quality

- `REFUSE` префикс встречается **3 раза** во всём mod коде → нет grep-friendly convention
- Background `Task.Run` posts silent on success — нет visibility что events doходят (`battle.stats_snapshot`, `HeroStateSync`, etc.)
- `EquipmentSync.PushAll` шлёт 11 background tasks за один call, ни одного лога

---

## B. Backend audit findings

### B.1 Atomic charge — ✅ безопасен по дизайну

`bannerlord_buy_action` использует `BEGIN IMMEDIATE` → `UPDATE viewers.points` + `INSERT module_actions` → `COMMIT`. Rollback корректно работает. Single-conn TX.

### B.2 Critical security gap — viewer-supplied `price`

`bannerlord.py:744-748` (player.spawn), `1218-1243` (join_tournament), etc. validate price только для конкретных action_types. **Действия без explicit validation branch принимают `data.price` от viewer'а напрямую:**

```python
price = int(data.get("price", 0))   # line 1306 — viewer-controlled
```

Affected (frontend может послать price=0, charge не произойдёт):
- `world.trigger_event` — **в `_PURCHASABLE_ACTIONS`** но никакой server-side enforcement
- `player.heal`
- `player.modify_attribute` (есть лимиты `MAX_ATTRIBUTE_POINTS_PER_ACTION` но не price)

**Сегодня fix:** server-side `ACTION_PRICES` table с explicit entries, fallback REFUSE для остальных.

### B.3 No refund on mod failure

`module_api.py:352-393` `/ack` endpoint:
```python
await db.ack_action(action_id, success=False, error=...)
# updates module_actions.status='failed', returns 200
```
Viewer's `viewers.points` уже debited. Refund отсутствует.

**Полный fix:** task #21 — добавить refund logic в `db.ack_action(success=False)` → SELECT price из module_actions.data, UPDATE viewers.points += price, INSERT audit row.

### B.4 Stuck `dispatched` actions

`module_actions.status` transitions: `queued → dispatched → acked|failed`. Нет `processing` или sweeper для `dispatched > N min`. Если мод упал между fetch и ACK — action stuck forever, viewer заплатил.

### B.5 Hero.Gold double-spend race

Между `_fetch_hero_gold` cache read (line 419 в backend) и mod's actual `GiveGoldAction.ApplyBetweenCharacters` — есть окно. Viewer spamит 2× `hero.create_clan` (1M каждый) → backend оба раза видит 1M cache (один write пока не пришёл) → оба enqueue → mod отказывает второй → refund нет (см. B.3) → viewer потерял 2M крустиков.

### B.6 Manifest events без handler

`_adapter.py` декларирует но не обрабатывает:
- `hero.kingdom_created`
- `hero.clan_left`
- `hero.kingdom_left`
- `hero.clan_joined`
- `hero.kingdom_joined`
- `hero.party_created`

Mod пушит → `_adapter.handle_event` логирует `unhandled event type=...` → backend cache (`bannerlord_heroes.clan_name`) stale. UI не отражает kingdom create до следующего `player.state_update`.

**Сегодня fix:** добавить handler stubs которые делают UPDATE clan_name/kingdom_name.

### B.7 Cooldown coverage gap

Только `power.activate` и `player.spawn` cooldowned (line 1316-1330). Spam-prone без CD:
- `hero.recruit_troops` (300💎 за call)
- `player.heal`, `player.equip_item`
- `hero.add_focus`, `hero.add_attribute`

Tracked в task #28 (per-user cooldowns rework).

### B.8 Logging gaps

- `module_api.py:227-262` event loop — per-envelope exception не logged (`logger.exception`)
- `bannerlord.py` refuse paths inconsistent — некоторые с `REFUSE` prefix (line 993), большинство без
- No queue-depth telemetry — если mod offline 10 min, backlog растёт silently

---

## C. Frontend audit findings

### C.1 Double-fire — `_bannerlordBuyAction` без in-flight guard

`viewer.js:3297` — no `_bnrActionInFlight` flag. Rapid double click → 2 POSTs → 2 charges → 2 actions enqueued. Mod может оба обработать или один отказать (race с другим), but backend оба раза успешно charged.

Affected buttons (нет own debounce): summon ally/enemy, power.activate, tournament.bet, marry/divorce, recruit, set_class, leave_clan, create_party, и тд.

Оптимистический UI guard есть только в одном месте (`viewer.js:1875` progression модал).

**Сегодня fix:** обернуть `_bannerlordBuyAction` в `_inflightSet` (per actionType key).

### C.2 Сломанный HTML — random equip

`viewer.js:1428-1433` — `<button id="bnr-random-horse">` открывается но **не закрывается `</button>`**. Браузер auto-recovers DOM, но click handler / tooltip могут behave inconsistent.

### C.3 Все catch блоки silent

`viewer.js:1247, 2652, 2691, 2739, 2825, 3220, 3292, 3335, 2027, 2133` — все ловят без `console.error/warn`. При сетевой ошибке viewer видит «Ошибка сети» (или ничего), debug невозможен без F12 + breakpoint.

**Сегодня fix:** `console.warn('[BNR <fn>]', err)` в каждом catch минимум.

### C.4 Stale state в модалах

`_bannerlordLastHero` invalidated только следующим poll (8s). Модалы (`_openBannerlordProgressionModal`, etc.) читают синхронно при open. Если открыть на 7-й секунде цикла — данные стары.

**Future fix:** trigger fresh `loadBannerlordHero` на modal open, render after.

### C.5 Buff/cooldown ticker drift

`viewer.js:1216-1234` — client-side decrement counter. Server-side absolute time queried 2.5s. Browser tab throttled → counter undercounts → power «unlocked» когда реально CD active → click → backend rejects.

**Future fix:** store `expires_at_ms = Date.now() + remaining_s*1000`, compute remaining from `Date.now()` каждый tick.

### C.6 Стримеры-actions в `_PURCHASABLE_ACTIONS`

`world.broadcast_message`, `world.trigger_event` — должны быть admin-only, но в frontend нет проверки role.

### C.7 Дубли constants

`MOUNTED` set defined в 2 местах (`viewer.js:1403` + `:2621`) — может drift.

---

## D. Что fixим сегодня (logging-only sprint)

User explicitly asked: «сделай логгирование всех спорных моментов». Apply следующие изменения без архитектурных правок:

### D.1 Mod (C#)

- **Convention REFUSE prefix** для всех silent return paths в handlers — grep-friendly.
- **Background Task.Run success logs** через counter (`HTTP push #N succeeded` every 50, не каждый).
- **`ClanUpgradesBehavior` lock** — atomic-swap для thread-safety (необходимо для prod).
- **EquipmentSync aggregate log** — одна строка вместо 11.

### D.2 Backend

- **`logger.exception`** в `module_api.py:227-262` event loop catch.
- **REFUSE prefix** для backend refusals (`hero.create_clan`, `hero.upgrade_gear`, etc.) — unify через helper.
- **Manifest event stubs** для 6 unhandled events (UPDATE clan_name/kingdom_name).
- **Action_id в логе** при enqueue + ACK для трассировки.

### D.3 Frontend

- **`console.warn('[BNR <fn>]', err)`** во всех silent catches.
- **In-flight guard** в `_bannerlordBuyAction` (single-flight per actionType).
- **HTML fix** — `</button>` closing tag в random-equip.
- **Backend `result.message` в console** даже на success — full audit trail.

---

## E. Tasks created (для последующих sprint'ов)

| Task ID | Что |
|---|---|
| #30 | Mod: REFUSE prefix + background push counter |
| #31 | Mod: ClanUpgradesBehavior lock — atomic-swap |
| #32 | Backend: server-side ACTION_PRICES table (security) |
| #33 | Backend: 6 manifest event handlers (clan_left etc.) |
| #34 | Backend: action_id tracing logs |
| #35 | Frontend: in-flight guard `_bannerlordBuyAction` |
| #36 | Frontend: HTML fix `</button>` + silent catch logs |
| #37 | Frontend: `expires_at_ms` cooldown ticker |
| #38 | Backend: dispatched action sweeper |
| #39 | Backend: Hero.Gold mutex (per-user serialization) |

---

## F. Где мы НЕ нашли проблем

- Multi-tenant isolation — `channel_id` last consistent, ни одной cross-tenant утечки в bannerlord queries
- Atomic charge — `BEGIN IMMEDIATE` + single-conn TX чист
- `_bnrDetailsAttr` + bind pattern — preserves `<details>` state корректно
- Destructive actions (leave_clan, divorce, make_baby, set_gender, create_party) — все `confirm()` обёрнуты
- `_stopBannerlordPolling` — все 5 intervals чисто чистятся, нет leak
- Sprint 5.28 ConcurrentDictionary fixes на KillRewardBehavior — корректны
- Sprint 5.28 negative roster repair pass — работает

---

## Reference: full punchlist в audit-agent output

Для углублённого investigation — три agent reports выше дают полный список (~50 findings across 3 layers).
