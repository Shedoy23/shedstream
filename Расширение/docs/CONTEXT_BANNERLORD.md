# Bannerlord Module — Context (chat handoff)

**Назначение:** для чата по Bannerlord-модулю. Для общей extension
работы — см. `CONTEXT.md`. Для RimWorld — `CONTEXT_RIMWORLD.md`.

**Last updated:** 2026-06-16 (tournament queue reconcile on save-load, bug #18 —
см. «2026-06-16» секцию ниже. До этого: 2026-06-15 save-load sync + per-save
state persistence + forge reforge-quality.)

## 2026-06-15 — Save-load sync + per-save persistence

Проблема: при загрузке сейва (особенно ДРУГОГО на том же канале) фронт показывал
стейт прошлой сессии — мод не делал полного ре-синка, а backend-only стейт жил по
ключу (channel, username) без привязки к сейву.

Исправлено:
- **Полный ре-синк на загрузке** (`MainCampaignBehavior.OnGameLoadFinished` →
  `ResyncAdoptedHeroes`): чистит hash-кэш зеркала + re-push `HeroStateSync` +
  `EquipmentSync` для всех [BLink]-героев. Покрывает game-derivable стейт
  (клан/лидер/король/золото/навыки/гир) — он берётся живьём из игры.
- **Per-save персистенция backend-only стейта** (`HeroProfileBehavior`, SyncData
  в файле сейва): class_key / combat_stance / gear_tier / retinue. Хендлеры
  ловят значение на действии (set_class/set_combat_stance/upgrade_gear/recruit/
  train; имена троопов резолвятся из troop_id), `OnGameLoadFinished` ре-пушит
  `hero.restore_profile` → backend `_on_restore_profile` перезаписывает класс +
  heroes.combat_stance/gear_tier + пересобирает bannerlord_retinue.
  - **Требует СОХРАНЕНИЯ игры** — SyncData пишет в файл сейва на save (автосейв в
    реальной игре делает сам; в быстрых тестах без сохранения — не персистится).
- **Forge → reforge-quality:** перековка надетого предмета на +1 ступень качества
  (Базовое→Хорошее→Шикарное→Легендарное, 20k💎/шаг), бейджи качества в
  Экипировке/Кузнице (m77 `quality` колонка + EquipmentSync push с учётом
  модификатора в статах). Вариант A: апгрейд тира → строго базовая броня.
- **Frontend no-hero fix:** на сейве без героя чистятся вкладки (#bnr-pane-*-body),
  иначе залипала старая карточка.

Gotchas (важно):
- **Новый mod→backend event = объявить в `manifest.yaml` `events:`** (иначе
  `event_not_in_manifest`, backend дропает до хендлера). Укусило 2× (см. CLAUDE.md).
- **Load latency:** ре-синк пушит всех героев пачкой + фронт-poll 8с → на загрузке
  стейт обновляется с лагом ~10с; «Обновить данные» — мгновенно. На одном сейве
  (обычная игра) незаметно.

clan_upgrades — ТОЖЕ per-save (2026-06-15, доведено): мод покупку не видит, но
`ClanUpgradesBehavior` фетчит owned-список → зеркалит в SyncData → на загрузке
`RestoreOwnedFromSave` пушит `hero.restore_clan_upgrades` → backend MERGE'ит
(INSERT OR IGNORE, не удаляет новые покупки). Новый сейв → пусто; главный →
восстановлено. Так backend-only стейт (класс/стойка/тир/свита/клан-апгрейды) ВЕСЬ
per-save через SyncData. (Был баг: вайп без restore сносил clan_upgrades+свиту на
смене сейва → потеря покупок зрителей; восстановили из daily-бэкапа.)

Остаточные мелочи (не делаем): casualty свиты самочинится на след. recruit/train;
старая свита до 2026-06-15 в SyncData не попадала (на смене сейва уйдёт пока не
переберётся). Прочие RESETTABLE-таблицы (auctions/heirs/marriage) — транзиентные,
сброс на смене сейва корректен.

## 2026-06-16 — Tournament queue reconcile (bug #18)

Тот же класс рассинхрона сейв↔backend, что и per-save выше, но с турнирной
очередью. Симптом (#18): зритель записался в турнир, но не попал в него.

Корень: in-game очередь — per-save (SyncData `blink_tournament_queue_v1`),
backend-очередь — durable. Стример сейв-скамит (грузит сейв, сделанный ДО записи
зрителя) → in-game очередь откатывается, зритель молча выпадает; расширение всё
равно показывает «в очереди» (читает backend-зеркало) → зритель не перезаписывается
→ турнир идёт без него. Доказано по логу: kuro joined 18:44 → SyncData load 18:46
restored 2 (pre-join) → турнир 22:37 без него.

Фикс: на `OnSessionLaunched` (после SyncData-restore) мод фетчит backend-очередь
(новая мод-facing `GET /api/bannerlord/tournament/queue-usernames`, зеркало
`clan-upgrades/all-owners` — channel_id-query без JWT) и **домерджит** недостающих
в `_queue` (резолв героя через HeroLookup; dead/missing — skip; dedup по Hero;
лимит 16). Merge-only, очередь не чистит → откат за уже прошедший турнир не ломает
очередь из того сейва. Backend — source of truth «кто записался». Не manifest-event
(это GET-фетч). Код: `TournamentQueueBehavior.FetchAndMergeBackendQueueAsync` +
`MergeBackendQueue` (мутация `_queue` на main-thread через MainThreadDispatcher).

Статус: задеплоено (backend + мод DLL md5 217B4F88), **в игре не проверено** —
после рестарта Bannerlord ждёт теста на стриме (лог `[tournament] backend
reconcile: +N merged`).

## ⚠️ ОБЯЗАТЕЛЬНЫЙ REFERENCE для новых фич

**Authoritative source-of-truth:**
```
https://github.com/Lait96/Bannerlord-Twitch-lait
```

При **любой** новой Bannerlord фиче — **сначала проверить как у Lait**,
потом адаптировать (не копировать построчно). Подробный workflow
+ mapping таблица + anti-patterns: [BANNERLORD_BLT_REFERENCE.md](./BANNERLORD_BLT_REFERENCE.md)

---

## TL;DR

Второй gaming-модуль платформы. Зрители adopt'ят NPC героя в Bannerlord
(имя hero = `[BLink] {viewer_login}`), выбирают **культуру** + **класс**
(13 классов) с подходящим snar'ем и passive/active powers, тратят валюту
из стрима на:

- **Боевое:** призыв в бой (за/против стримера) — **50/100💎** + cooldown 30s,
  4 active powers, BLT-aligned kill rewards × 0.5 (2500/2500 gold/xp + level
  scaling + kill streaks 5/10/15), participation rewards (5000💰/5000XP
  победителям, 2500XP проигравшим), spawn anchor около стримера
- **Экономику:** конвертация крустиков в Hero.Gold или skill XP, random equip
  (T5-T6: weapon 1M / armor 500K / horse 1M)
- **Прогрессию:** gear upgrade (6 tier), focus в skills, attribute points,
  clan upgrades (BLT-style 10 catalog items с static effects через model replacement)
- **Социальное:** clan create/join/leave, kingdom create/join/leave,
  MobileParty creation, **gender swap, marriage, divorce, make baby + family tree**
- **Свита:** basic + elite retinue (BLT pattern, 5 slots, 3× cost для elite,
  ring 60°×2m вокруг hero, skip в hideout)
- **Турниры:** queue + 16-man bracket + bets
- **Имена в бою:** Agent.Name через reflection — hero=`@username`, retinue=`Trooper (@username)`

**Архитектура:** C# Bannerlord-submodule (`BannerlordLink/`,
prod-mirror в `Modules/Shedoy23.BannerlordLink/`) ↔ FastAPI backend
(`Расширение/backend/`) через Module API generic dispatcher
(`routes/module_api.py`) + Bannerlord-specific endpoints
(`routes/bannerlord.py`).

---

## Remaining feature backlog (BLT-parity gaps)

> **СЛЕДУЮЩЕЕ (готово к сборке): «Армия» MVP — спека `ARMY_MVP_SPEC.md`.** Дизайн
> зафиксирован (Вариант A: армия КОРОЛЕВСТВА на vanilla `Kingdom.CreateArmy`, низкий
> LGPL-риск, НЕ BLT-независимая), физибилити проверена 2026-06-14. Свежий чат —
> читай спеку, заходи сразу в C#. Compliance ок.

> Консолидировано 2026-05-29. Детальный аудит каждой фичи (что у BLT, что у
> нас) — `BLT_RC22_REFERENCE.md` секции C.x (ссылки в таблице). Оценки —
> грубая прикидка, не обязательство. Делать сверху вниз (от короткого).

| # | Фича | Оценка | Reference | Суть |
|---|---|---|---|---|
| ~~1~~ | ~~**KingdomTaxBehavior**~~ | ✅ DONE 2026-05-29 | C.5 | Король-viewer задаёт налог 0-100% (Kingdom-панель), вассальные кланы королевства ежедневно платят % дневной прибыли в казну короля. `KingdomTaxBehavior` (mod) + `kingdom.set_tax_rate` action + m59 `kingdom_tax_pct`. |
| ~~2~~ | ~~**TrainingBehavior**~~ | ✅ DONE 2026-05-29 | C.17 | Адаптировано под нашу backend-свиту (не MobileParty): `hero.train_troops` — bulk-upgrade ВСЕХ слотов свиты на тир за раз (all-or-nothing, динары, переиспользует recruit UpgradeTargets-логику). Прямое действие вместо пассивного фонда (наша свита ≠ MobileParty). Mod `TrainTroopsHandler` + кнопка «🎯 Тренировать свиту». |
| 3 | **Two retinues (Retinue2)** | ~3-5 дн | C.7 (стр.520,586) | Вторая независимая свита (basic + elite раздельно). У нас одна (5 слотов). Expansion. |
| 4 | **BLTLogsBehavior** | ~1-2 нед | C.26 (стр.1219) | Лента событий (kills/levelup/prisoner/death) → feed history. ~1100 LOC у BLT. У нас НЕТ log feed. |
| 5 | **BLTSettlementUpgradeBehavior** | ~1 нед+ | C.9 (стр.642) + UpgradeBehavior C.25 | Апгрейд поселений (prosperity/loyalty/security/food/militia/tax бонусы daily tick). У нас ClanUpgrades — меньший scope. |

**Отложено (deferred, не в очереди):**
- **Vassal income share — UI surfacing.** Механика РАБОТАЕТ in-game (мод skim'ит
  25% дневной чистой прибыли вассала → master, см. `VassalAutoFollowBehavior.
  OnDailyTickClan`), но во фронте (vassals panel) не отображается «получено с
  вассалов: X». Нужен backend-event + хранение + рендер. Низкий приоритет.

**Недавно закрыто (чтобы новый чат не переделывал):**
- **PRICE-FIX power.activate (2026-06-14)** — баг "написано одно, списано другое":
  `power.activate` сидел в `ACTION_PRICES_DEFAULT` (flat 50💎), бэк списывал 50 за
  ЛЮБУЮ активку, фронт показывал реальные 100–350 из хардкода `BNR_POWER_PRICES`.
  Фикс (тонкий фронт): `POWER_PRICES` на бэке = единый источник; per-power цена
  enforced в `_prepare_action`, бэк отдаёт `price` в `current_powers[]`, фронт читает
  `p.price` (хардкод удалён из `viewer.js`). Тест-кейс в `test_bannerlord_buy_action.py`
  (rage=300, heal_burst=100, unknown→refuse), 34/34. Задеплоено прод (бэк+фронт).
- BLT-RC22 refactor **Stages 0-7** (audio mute, AgentPfx persistent particles,
  centralized DamageHook filter, permadeath prevention, mount protection,
  siege/militia engine fixes, summon mount guards, RetinueAllowed guards,
  VassalAutoFollowBehavior). См. `REFACTOR_PLAN_BLT_RC22.md`.
- **FLICKER-FIX v7** — Hero pane секции больше не мерцают (split volatile
  stats grid vs stable sub-slots в `viewer.js`).
- **Vassal income share** (механика, см. deferred выше про UI).
- **COMPAT-3** — `BANNERLORD_COMPAT_MATRIX.md` (версии/патчи/конфликты).
- **ARCH-1** — `ARCH_DATA_OWNERSHIP.md` (разбор SQL-vs-save split-brain).

---

## Экономика — две валюты

| Валюта | Где живёт | Что покупает |
|---|---|---|
| **Крустики ⦷** | Backend `viewers.points` | Призыв (**50/100⦷** после 5.27i), powers, retinue recruit (100/300⦷), XP/gold конверсия, бесплатные actions (clan/kingdom/party/family — 0⦷) |
| **Hero.Gold 💰** | In-game | Gear tier (50K–1.5M), random equip T5-T6 (**500K-1M** после 5.27o), focus (30K–75K), attributes (50K), retinue troops (5K–80K basic / ×3 elite), clan (1M), kingdom (5M), party (200K), tournament entry (5K), join clan/kingdom (50K/100K), **gender swap (50K), marriage (50K), baby (100K)** |

**Source of truth:**
- Крустики: backend `viewers.points`, atomic charge внутри `/action` TX
- Hero.Gold: мод (`hero.Gold` через `GiveGoldAction.ApplyBetweenCharacters`)
- gear_tier / clan / kingdom / family_info: mod пушит `hero.*_changed`
  event → backend cache. Mod source-of-truth.

---

## Sprints статус — 40+ закрыто (5.0 → 5.27v)

### Migrations applied (prod)
- **M14–M28** — base schema (heroes/skills/attrs/equipment/classes/powers/
  tournament/retinue/focus/clan_info/kingdom_info)
- **M29** — pets schema v2 (face+aura slots, svg_path, scarf→body)
- **M30** — pets catalog +15 items
- **M31** — pets deprecate 4 misfit items
- **M32** — pets hard-delete misfits
- **M33** — tts_messages table
- **M34** — tts.audio_data BLOB (server-side gTTS)
- **M35** — bannerlord_clan_upgrades_catalog + _owned (BLT clan upgrades)
- **M36** — bannerlord_heroes + `is_female INTEGER`, `family_info_json TEXT`
- **M37–M41** — pets v3 clean-slate + BLT-parity achievements/auctions/heirs/active-powers
- **M42** (Sprint 5.31 #45) — `bannerlord_boosty_subscribers` (PK channel_id+twitch_username,
  tier 1/2/3, optional note). Streamer ведёт список вручную через **/streamer/dashboard**
  (cookie-сессия). Boosty подписчики получают те же price/reward boost'ы что Twitch sub.
  Perk chain: broadcaster → moderator → **Boosty** → Helix Twitch sub → viewer.
  Endpoints: `/api/dashboard/boosty/subscribers` (GET/POST), `.../bulk` (POST).
  In-memory cache в `routes/bannerlord_boosty.py` с per-channel invalidation
  on mutation, чтобы lookup в buy_action был sub-ms.

### Sprint 5.31 #45b–#45f — Boosty rollout + 4 раунда аудита

- **#45b** — Boosty admin перенесён в /streamer/dashboard (cookie-auth) +
  tier-бейдж под ником в шапке расширения (`TS1`/`BS2`/...) через
  `/api/viewer/perks`.
- **#45c (logging gaps audit)** — perk-resolved INFO лог на каждой покупке;
  `[boosty cache]` per-channel load count; cookie session verify trio
  (malformed/HMAC mismatch/expired); twitch_subs 429 dedicated branch;
  frontend `[perks]` dbg вместо silent-catch. Smoke-verified в prod логе.
- **#45d (HIGH audit, 9 fixes)** —
  *MOD:* TournamentQueueBehavior static field → `ConditionalWeakTable<Settlement,...>`;
  `_partyRestores` mission-keyed filter (no cross-mission leak); `_retinueOwners`
  `ConcurrentDictionary` → `ConditionalWeakTable<Agent,...>` (GC auto-evict);
  ActionPoller OCE re-throw (без ACK на shutdown — нет fake refund).
  *BACKEND:* tournament.join_tournament status+queue+pending dedup внутри
  BEGIN IMMEDIATE; charge — atomic `UPDATE ... WHERE points >= ?` + rowcount
  (multi-worker safe); shared aiohttp.ClientSession (new `http_session.py`)
  закрывается в `on_shutdown`; pubsub + twitch_subs мигрированы на shared;
  DEV_MODE double-gate `RIMLINK_ENV != prod` (.env set on prod).
- **#45e (MED audit, 13 fixes)** —
  *MOD:* DamageHookPatch periodic blow counter (life-sign против Harmony
  binding break); SetAgentDisplayName multi-field reflection + periodic
  re-warn; OnHeroKilled — ExtractUsername + skip non-adopted; BackendClient
  `JsonConvert.SerializeObject` вместо `string.Format`; HeroStateSync
  per-property try/catch; ActionPoller dedup ring (action_id ConcurrentDict
  TTL 10 мин, max 2000 — закрывает sweeper double-debit).
  *BACKEND:* tournament.bet dedup внутри BEGIN IMMEDIATE; module_api auth
  trio unified `auth_failed` (timing oracle protection); cases.py preview
  endpoints per-IP rate-limit 60/min.
  *FRONTEND:* 5 setInterval → safeInterval; escape `${title}`, `${a.item_icon}`,
  `${it.icon}` defensively.
- **#45f (CodeGraph dead-code audit)** — удалено 387 строк dead кода:
  `_openBannerlordBoostyModal` (202 строки в viewer.js, orphan после переноса
  на dashboard); 3 JWT endpoint'а `/api/streamer/boosty/*` + helper
  `_require_streamer_role` (158 строк в bannerlord_boosty.py — заменены
  cookie-auth dashboard'овскими); `migrate_to_pool` декоратор (27 строк
  в db_pool.py, 0 callers). Все non-actionable findings (auction discount
  intentional; RimWorld legacy routes — внешний C# мод может звать;
  `resolve_channel_id_or_default` — overlay endpoints OK для single-tenant).

### Action handlers (28 real + stubs)
**Hero progression:**
- `hero.create` — adopt wanderer + culture filter + [BLink] prefix
- `hero.set_class` — apply class equipment + gear_tier aware
- `hero.upgrade_gear` — 6-tier replace (Hero.Gold cost)
- `hero.add_skill` / `hero.add_focus` / `hero.add_attribute`
- `hero.recruit_troops` — basic OR elite retinue (is_elite flag)

**Family system (Sprint 5.27a-c):**
- `hero.set_gender` — gender swap (50K💰, auto-flip spouse если same-sex)
- `hero.marry` — random suitable NPC (50K💰, NPC переходит в hero.Clan)
- `hero.divorce` — free, sets Spouse=null обеим сторонам
- `hero.make_baby` — pregnancy (100K💰, max 5 alive children, `MakePregnantAction.Apply`)

**Clan / Kingdom / Party:**
- `hero.create_clan` (1M💰) / `hero.create_kingdom` (5M💰) / `hero.create_party` (200K💰)
- `hero.leave_clan` / `hero.leave_kingdom` (free)
- `hero.join_clan` (50K💰) / `hero.join_kingdom` (100K💰)
- `hero.join_tournament` (5K💰)

**Battle / combat:**
- `player.spawn` — summon (ally 50⦷ / enemy 100⦷ после 5.27i, CD 30s)
  - Anchor: ally — 3m perpendicular от Agent.Main, alternating L/R по hash
  - Anchor: enemy — 10m forward от Agent.Main + face-to-face
  - Hideout: skip position anchor + block enemy summon (5.27r)
  - Retinue: ring 60°×2m вокруг hero, skip в hideout (5.27n)
  - Agent rename: `@username` для hero, `Trooper (@username)` для retinue
    через reflection `AccessTools.Field(typeof(Agent), "_name")`
- `player.heal` / `player.give_item` / `player.equip_item` / `player.modify_attribute`
- `power.activate` — 4 active powers (heal_burst/shield_break/rage/retribution)
- `tournament.bet` — backend-only

### Campaign + Mission behaviors

- **MainCampaignBehavior:**
  - HeroKilledEvent → player.died
  - HeroLevelledUp → HeroStateSync.Push
  - OnSessionLaunched + OnGameLoadFinished → push session_start
  - **MapEventEnded** (Sprint 5.27l) — выкидывает [BLink] viewer-героев
    из MainParty.MemberRoster после боя через `EnterSettlementAction.
    ApplyForCharacterOnly(HomeSettlement)` (BLT pattern, защита от
    phantom-reference)
  - HourlyTickEvent — DISABLED (5.27h.2 — ломал MainParty в минус)

- **PowersMissionBehavior** (без изменений)

- **KillRewardBehavior** (полностью переделан в 5.27g — BLT × 0.5 scale):
  - Personal kill: 2500💰 + 2500 XP × horseFactor × levelBoost
  - Retinue kill: 1250💰 owner, +25 HP heal самому retinue (BLT pattern), 0 XP
  - Killed (наш hero убит) → +1000 XP consolation × levelBoost (BLT XPPerKilled)
  - Level scaling: `(1 - delta/30)^(-10 × n)`, cap 5×, MinGold clamp 0.5
  - Kill streaks: 5/10/15 kills → +2.5K/+5K/+10K bonus, reset on death
  - **Participation** (Sprint 5.27k, fires в OnEndMission):
    - Win: +5000💰 +5000 XP (всем участникам)
    - Loss: +2500 XP consolation, **без gold штрафа** (newbie-friendly)
    - Skip на DefenderPullBack
  - **PartyRestore** (Sprint 5.27e/j fix):
    - Removal из current party ВСЕГДА, не только если есть OriginalParty
    - No-original-party fallback: `EnterSettlementAction.ApplyForCharacterOnly
      (HomeSettlement)` (BLT pattern — даёт hero legit location, нет phantom)
  - Agent rename via reflection при spawn (Sprint 5.27q)

- **ClanUpgradesBehavior** (Sprint 5.26c) — static `Current` accessor,
  `GetBonusFor(hero, effectKey)`, daily tick применяет renown +
  ChangeClanInfluenceAction. Catalog из 10 BLT-style upgrades T1-T5.

- **BLUpgradeModels** (Sprint 5.26d) — model replacements через
  `campaignStarter.AddModel`: `BLPartySpeedModel`, `BLPartySizeLimitModel`,
  `BLClanTierModel`. Subclass TaleWorlds models, delegate to `_previous`,
  добавляют bonus от ClanUpgradesBehavior. Включает overrides для
  Naval DLC (`FindAppropriateInitialShipsForMobileParty`),
  `CalculateInitialRenown → int`, `HasUpcomingTier → (ExplainedNumber, bool)`.

- **TournamentQueueBehavior** + **TournamentMissionBehavior** (без изменений)

### Harmony patches (без изменений)
- `DamageHookPatch`, `IsSideDepletedPatch`, `TournamentParticipantsPatch`

### Helpers
- `HeroNaming.cs`, `HeroLookup.cs`, `PowerCache.cs`, `ActiveBuffState.cs`
- **`HeroStateSync.cs`** (расширен 5.27c):
  - Payload включает: gold/level/clan/kingdom/skills/attributes/
    clan_info/kingdom_info + `is_female` + `family_info` {spouse, children[],
    father, mother, sibling_count}
- `EquipmentSync.cs` — без изменений

### Backend
- `routes/bannerlord.py` — 12+ endpoints + clan-upgrades CRUD
- `modules/bannerlord/_adapter.py` — 25 event handler types
- Server-side price maps:
  - `RANDOM_EQUIP_HERO_GOLD`: weapon=1M / armor=500K / horse=1M (5.27o T5-T6)
  - `SPAWN_PRICES`: player=50⦷ / enemy=100⦷ (5.27i ×0.5)
  - `POWER_COOLDOWNS["player.spawn"]`: 30s (5.27i, было 120s)
  - `GENDER_SWAP_COST` / `MARRIAGE_COST`: 50K
  - `BABY_COST`: 100K
- `routes/bannerlord.py` `/my-hero` (Sprint 5.27v):
  - Attributes keys normalized к PascalCase via `_to_pascal` helper
    (single source of truth — frontend всегда видит `Vigor`, `Intelligence`
    даже если БД хранит lowercase из engine StringId)
- TTS endpoints в `routes/tts.py` (sprint 5.23, server-side gTTS)
- Сезонные призы dice/duel/RPS/TTT (sprint 5.25): 300k/200k/100k, 2 недели,
  ELO start 1000, prize gate ≥1100

### Frontend (`viewer.js` ~3700 строк)

**Hero card layout (Sprint 5.19 redesigned):**
- Семантические секции: Бот / Магазин / Канал / Bannerlord (modal-button)
- Inline shop+quests+promo modals
- Pets — universal pet system с overlay items (face/aura/body slots),
  walking pets в overlay (sway animation, full username)

**Bannerlord hero card:**
- Header + alive/prisoner + culture + location
- Stats grid: 💰 Динары / ⭐ Уровень / 🛡 Снаряжение T1-T6 + inline ⚒ upgrade /
  🏰 Клан ⚙ / 👑 Королевство ⚙ + 🛡 Броня summary
- Battle banner (in_battle) — HP bar + kills + gold_earned + xp_earned
- Buff HUD
- Class picker (13 классов)
- Active power buttons (cooldown-aware)
- Summon buttons (📯 50⦷ / ⚔️ 100⦷ — 5.27i)
- **🧬 Профиль и семья** modal — gender swap / marriage / divorce / family tree
  + кнопка зачать ребёнка (Sprint 5.27a-c)
- **🛡 Улучшения клана** modal — Sprint 5.26b
- **🎯 Прогрессия** modal — attribute groups + skills + per-row + buttons,
  optimistic UI update on click (Sprint 5.27t), 5s reopen delay
- Equipment + Свита details (collapsible, persisted state)
  - Свита кнопки показывают: `100💎 + 5 000💰` + "не хватает X💰" при недостатке (5.27h)

**Shop card:**
1. 🎁 Случайный товар (T5-T6 после 5.27o)
2. 💰 Динары + 📚 Опыт конверсии

**Mini-games (Sprint 5.24):**
- Дуэли — matchmaking queue + BO3 + 10s timer (RPS-style ELO)
- Кубики — 3 раунда + re-roll одного кубика + 10s timer + auto-expire on poll
- TTT — 4×4 grid + BO3 + 10s timer
- All games have lazy expiration through generic /poll endpoint

**TTS (Sprint 5.23):**
- "🔊 Озвучить сообщение" в Канал секции (3-я карточка)
- Server-side gTTS Python lib → MP3 BLOB → frontend Audio() в overlay
- Web Speech API не работает в OBS browser source — пришлось переехать на server-side

**Polling:**
- `/api/bannerlord/status` — 8s
- `/api/bannerlord/my-hero` — 8s
- `/api/bannerlord/my-buffs` — 2.5s
- `/api/bannerlord/battle-status` — 2s
- Pet overlay — 1s

**Overlay (overlay.html):**
- BLT-style cards bottom-row (HP-bar + side color + state glow + sort)
- TTS audio play (Audio element, OBS must enable "Control audio via OBS")
- Walking pets с full username

### Mobile (`mobile.html`)
Parity с `extension.html`.

---

## 1.4.5 / 1.3.15 история (важно!)

**21 мая 2026** TaleWorlds выпустили **BL 1.4.5 + War Sails 1.2.5** (seaborne
village raids + voiceovers). Steam обновил engine автоматически.

**Старый save (1.3.15) crash'нул на load** в 1.4.5 — TaleWorlds save format
не backwards-compatible на minor bumps. `Game Integrity is Achieved: False`.
**30+ community модов** (Diplomacy, ImprovedGarrisons, Vlandian Steel Reforged,
ItemQualityIndicator, BLSE и пр.) собраны под 1.3.15 — все падали.

**Решение:** user manually откатил Steam до 1.3.15 (Steam validation /
manifest manual). Сейчас all live на **1.3.15** (Build Version: v1.3.15.110062).

Наш мод собран против **1.4.5 references** во время короткого update window,
но binary-compatible с 1.3.15 — работает без proблем (см. логи: kill rewards,
summon, retinue, family — всё OK).

**Action item на будущее:** при следующем engine update — сначала закрыть
Bannerlord, отключить Steam auto-update, дождаться 1.4.5-compatible
community модов, потом upgrade'нуть и пересобрать наш мод.

---

## Recent sprints (5.19 → 5.27v) — детально

**Sprint 5.19 — UI redesign:** семантические секции extension.html
**Sprint 5.20 — Marriage 500 fix:** dropped `family_balance` из INSERT'ов, M8 dropped column
**Sprint 5.21 — Pets v2:** SVG creature + face/aura/body slots, walking overlay
**Sprint 5.22 — Pet polish:** aura particles, body color (no separate bg), frameless walk, slower, full username
**Sprint 5.23 — TTT (TTS):** server-side gTTS вместо Web Speech (OBS unfriendly)
**Sprint 5.24 — Mini-games rework:** dice 3 rounds + reroll + 10s timer, duel matchmaking + BO3, TTT 4×4 + BO3
**Sprint 5.25 — Season prizes:** 300/200/100k, 2 weeks, ELO 1000 start, prize gate ≥1100
**Sprint 5.26 — Clan upgrades (BLT-style):**
  - 5.26a: schema + 10 catalog items + purchase (M35)
  - 5.26b: frontend modal в bannerlord card
  - 5.26c: mod-side ClanUpgradesBehavior daily ticks (renown + влияние)
  - 5.26d: static effects через model replacements (BLPartySpeedModel etc.)
**Sprint 5.27 — Family + battle rework:**
  - 5.27a: Hero gender swap (50K💰, BLT style)
  - 5.27b: Hero marriage to NPC + divorce
  - 5.27c: Children + family tree (M36, MakeBabyHandler)
  - 5.27d: Retinue spawns NEAR hero (ring 60°×2m), не в backline
  - 5.27e fix: PartyRestore removal безусловно (даже если no original party)
  - 5.27f: Hero spawn anchor near streamer (Agent.Main + perp offset)
  - 5.27g: Kill rewards BLT-aligned × 0.5 (2500/2500 + level scaling + streaks)
  - 5.27h: HourlyTick safety net (потом DISABLED в .2, ломал MainParty)
  - 5.27h.1: Retinue UI heroGold accessor fix (`.hero.gold` not `.gold`)
  - 5.27h.2: HourlyTick eviction reverted (phantom reference)
  - 5.27i: Summon prices × 0.5 + cooldown 120→30s
  - 5.27j: BLT-pattern restore via EnterSettlementAction для viewer без party
  - 5.27k: Participation reward (BLT WinGold × 0.5, +XP loss consolation, no gold penalty)
  - 5.27l: Cleanup tied to MapEventEnded (после боя, не hourly)
  - 5.27m: Разрешили hideout combat (BLT block-list mode filter)
  - 5.27n: Skip retinue spawn в hideout (8-limit)
  - 5.27o: Random equip prices до T5-T6 (1M / 500K / 1M)
  - 5.27p: Enemy summon fallback + diagnostic + spawn position
  - 5.27q: Nickname над персонажами через reflection `Agent._name`
  - 5.27r: Hideout summon — skip anchor + block enemy
  - 5.27s: Diagnostic log для add_attribute REFUSE/QUEUE
  - 5.27t: Optimistic UI для add_attribute (immediate +1, 5s reopen delay)
  - 5.27u FIX: attribute lookup case-insensitive (lowercase в БД vs PascalCase в JS)
  - 5.27v: Single source of truth — backend normalize attr keys к PascalCase
    + runtime canary в frontend для contract drift

---

## Open / pending

**🐞 Баги из репортов зрителей (`!баг`, стрим 2026-06-14, 14 репортов):**
- ✅ **FIXED (ждёт деплой)** — политики/мир/налог = «Не состоишь в kingdom'е» для всех
  (#6 ethanenok, #7 kuro_gothic). Root: `handle_enact_policy` / `handle_make_peace` /
  `handle_set_kingdom_tax` читали мёртвые колонки `kingdom_id`/`is_king` (sync пишет только
  `kingdom_info_json`). Фикс: `_derive_kingdom()` в `bannerlord_diplomacy.py` деривит из
  info_json (тот же фикс, что в kingdom-state endpoint). **НЕ задеплоено.**
- ✅ **FIXED (ждёт in-game тест)** — **#10 окно голосования война/мир мелькает и исчезает**
  (shedoy23). Root (декомпиляция ванили): клик `ExecuteAction()→_onInspect→OnInspect()`, а
  `OnInspect` имеет 2 незащищённых null-разыменования (`_decision.ShouldBeCancelled()` при
  устаревшем решении + `Clan.PlayerClan.Kingdom` при безклановом игроке). Финализатор раньше
  просто глотал NRE → попап не открывался. Фикс: prefix на `OnInspect` гардит оба null'а →
  graceful `ExecuteRemove` вместо NRE; валидные решения идут в ваниль (голосование
  открывается). Финализатор теперь логирует полный стек (backstop). `KingdomVoteNotificationPatch.cs`,
  собрано+скопировано в игру. **Проверить:** рестарт Bannerlord → зритель предлагает войну →
  клик по колокольчику голосования должен ОТКРЫТЬ окно решения, а не исчезнуть.
- ✅ **FIXED (ждёт in-game тест)** — **#12 хил на турнирах → бесконечный бой** (shedoy23).
  Root: `ApplyPassivePowers` даёт каждому [BLink]-агенту `BASE_HP_MULT` (×2.5) + class
  `hp_multiplier` на спавне → в турнире агент почти неубиваем («пассивный хил»); плюс
  `player.heal` вообще не гейтился. Фикс: вынес детект арены/турнира в `Util/MissionContext`
  (`IsArenaOrTournamentMission` для spawn-гейтов + `IsArenaOrTournamentFight` для активок) →
  HP-множители НЕ накладываются в арене/турнире (ванильно-честный бой), `player.heal`
  refuse+refund в живом турнирном бою, `ActivatePowerHandler` теперь на том же хелвере.
  `body_scale`/`move_speed` в турнире пока остаются (не про хил). Собрано+скопировано.
  **Проверить:** турнир → стример получает/наносит обычный урон, бой заканчивается.
- ✅ **VERIFIED уже прикрыт** — **#14 смена класса в бою** (neyrahatomia). Гейт «нельзя сменить
  класс во время Mission» (`SetClassHandler.cs:106`, `Mission.Current != null`, Sprint 5.32)
  деплоен и работает: в стриме репорта сработал **21 раз** (REFUSE in_mission) vs 28 легальных
  смен на карте. Буквальный эксплойт (смена в бою) блокируется. Остаётся лишь смена **между
  боями** на карте → новый класс = свои power_keys со своим кд (стоит 60с кд смены класса,
  по сути штатно). Глобальный кулдаун на все пауэры — балансное решение, не баг; по запросу.
- ✅ **FIXED (deployed)** — **#8 нет прогрессии у части классов** (kuro_gothic: тяжёлый
  арбалетчик). Root: `_CLASS_PRIMARY_SKILL` (карта класс→primary-скилл для `_compute_class_level`)
  была рассинхронизирована с ростером — пропущены **4 реальных класса**: `heavy_archer`,
  `crossbow`, `heavy_crossbow`, `assassin` → `_compute_class_level` возвращал 1 навсегда (нет
  прогрессии). Лучник (#3) был в карте → починился; арбалетчиков пропустили. Фикс: добавил 4
  класса (`bannerlord.py`, skill-имена сверены с prod `bannerlord_skills`). Read-path — live
  сразу после деплоя бэка.
- ✅ **уже починено** — **#11 ставка на турнир залипает** (k0r0b14) — фикшено ранее (владелец
  подтвердил, что сейчас работает).
- ✅ **уже починено** — **#4 свита не обновляется при апгрейде** (shedoy23) — фикс 2026-06-13
  (`viewer-bannerlord.js:4606` — re-render свиты при любом изменении состава/тира), задеплоен.
- ⏭ **SKIP** — #13 дропдаун клана (neyrahatomia) — владелец решил, излишне.

(Источник: prod `viewers.db.bug_reports` ch=98319857. Шум — #1 тест / #2 трол / #5 «шортс» — уже resolved.)

**🔴 Production blockers:**
- **Sprint 5.2 — Compliance rebrand** перед public Twitch release
  (audit class_keys / power_keys / numeric values vs BLT LGPL,
  NOTICE.md, Extension submission)
- **Test 19 extend** — `test_multi_tenant_isolation.py` assertions
  для новых fields (clan_info_json / focus / attributes / retinue.is_elite /
  family_info_json / is_female)

**🟠 Features в очереди:**
- **Tavern summon (SummonInLocation)** — BLT 200+ строчный метод,
  `CampaignMission.Current.Location` API (Location-based spawn, не Mission)
- **Auto-summon 30 мин подписка** — viewer покупает window auto-spawn'a
- **Transfer clan leadership** — для leaders которые хотят покинуть клан
- **Party order commands** (BLT-level): siege/defend/patrol/raid/garrison
- **Party disband / stats inline**
- **Always-visible 3D nametag floating над head** — нужен custom MissionView
  (200+ строк рендера в 3D пространстве). Сейчас имя показывается только
  при hover/target (BLT pattern).

**🟡 Tech debt / polish:**
- **Sprint 4.10 Balancing** — после live data: cooldowns + active power values + tier costs
- **TTL для queued module_actions** — сейчас лежат вечно если mod не applied;
  нет refund при skip/expire (e.g. summon купил но вне Mission)
- 20+ handlers share username-extract pattern → `ActionHandlerBase`
- `KillRewardBehavior` accumulates 2 static registries (`_retinueOwners`,
  `_partyRestores`) — split на `MissionStateBehavior`?
- `bannerlord_buy_action` — 750-строчная мега-функция, dispatch table

**🔵 Wild ideas:**
- AI Advisors (rule-based MVP — Trade Advisor)
- Hero relations system
- Custom prize items в турнирах

---

## Stack
- **C# mod:** .NET Framework 4.8 net472 x64, Bannerlord **1.3.15** (откат с 1.4.5)
- **References:** TaleWorlds.{Core / Library / MountAndBlade / CampaignSystem /
  CampaignSystem.AgentOrigins / CampaignSystem.Party / CampaignSystem.Actions /
  Engine / Localization / ObjectSystem / DotNet}, Bannerlord.Harmony,
  Newtonsoft.Json, SandBox
- **Build:** `dotnet build` (~1-2 сек), output в
  `Modules/Shedoy23.BannerlordLink/bin/Win64_Shipping_Client/`
- **Backend:** FastAPI + SQLite + aiosqlite, supervisor на VPS 31.130.132.224
- **Frontend:** vanilla JS, no build (Twitch extension constraint),
  cache-bust через `?v=YYYYMMDDx` суффикс в HTML script tags

## File structure (mod)

```
X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\
└── Modules\Shedoy23.BannerlordLink\
    ├── SubModule.xml
    ├── config.json            ← module_token + channel_id (gitignored)
    ├── src\
    │   ├── BannerlordLink.csproj
    │   ├── BannerlordLinkModule.cs   ← MBSubModuleBase entry
    │   ├── MainThreadDispatcher.cs
    │   ├── Net\
    │   │   ├── BackendConfig.cs / BackendClient.cs / ActionPoller.cs
    │   │   ├── PowerCache.cs / ActiveBuffState.cs
    │   ├── Actions\ (28 real handlers + Echo + Registry)
    │   │   ├── AdoptHeroHandler.cs
    │   │   ├── SetGenderHandler.cs    ← 5.27a
    │   │   ├── MarryHandler.cs         ← 5.27b (also DivorceHandler)
    │   │   ├── MakeBabyHandler.cs      ← 5.27c
    │   │   └── ...
    │   ├── Models\
    │   │   └── BLUpgradeModels.cs      ← 5.26d
    │   ├── Behaviors\
    │   │   ├── MainCampaignBehavior.cs ← + MapEventEnded (5.27l)
    │   │   ├── ClanUpgradesBehavior.cs ← 5.26c
    │   │   ├── KillRewardBehavior.cs   ← BLT × 0.5 + participation (5.27g/k)
    │   │   └── ...
    │   ├── Patches\
    │   └── Util\
    │       ├── HeroNaming.cs / HeroStateSync.cs ← + family_info (5.27c)
    │       └── EquipmentSync.cs
```

Git mirror: `BannerlordLink/` (sync через `cp` после правок).

---

## Build + deploy cycle

```bash
# C# build (mirror в production folder)
cd "/x/SteamLibrary/.../Shedoy23.BannerlordLink/src"
"/c/Program Files/dotnet/dotnet" build BannerlordLink.csproj -c Release

# Restart Bannerlord (нет hot-reload).
# Логи: C:/ProgramData/Mount and Blade II Bannerlord/logs/rgl_log_*.txt
#       AppData/Roaming/Mount and Blade II Bannerlord/Logs/*.log

# Sync обратно в git-репо
cp "X:/SteamLibrary/.../Shedoy23.BannerlordLink/src/<file>.cs" \
   "C:/.../hopeful-agnesi-ea9afe/BannerlordLink/src/<...>/"

# Backend + frontend deploy на прод (FOR NEW CONTEXT: 31.130.132.224)
cd Расширение
tar -cf /tmp/sprintX.tar backend/routes/bannerlord.py frontend/viewer.js \
    frontend/extension.html frontend/mobile.html
scp /tmp/sprintX.tar root@31.130.132.224:/tmp/
ssh root@31.130.132.224 'cd /root/twitch-extension && tar -xf /tmp/sprintX.tar && supervisorctl restart twitchbot'

# Cache-bust frontend (sed bump)
sed -i 's/viewer.js?v=20260521u/viewer.js?v=20260521v/g' frontend/{extension,mobile}.html
```

## Лицензия BLT (важно!)

**BLT (LGPL 2.1)** — используем как **reference только**, не copy-paste.
- ✅ Идеи / архитектурные паттерны / API discovery / 5-10 строчные idioms
- ❌ Целые классы / method bodies / identical names+numbers

Наш `BannerlordLink/` — clean-room re-impl. **Перед public release**
(Sprint 5.2) — полный audit для финального compliance.

**BLT 5.2.4 source extracted** в `/tmp/blt-src/Bannerlord-Twitch-5.2.4/`
для reference во время dev (не commit'ить).

## Тестирование

См. `CONTEXT.md` §«Тестирование» — те же flows работают:
- `/dev` login + extension preview
- `curl /api/admin/dev/jwt` для preview tokens
- `TESTING_BYPASS_STREAM_LIVE=true` для actions без go-live

**Module test данные:**
- Channel: 98319857 (shedoy23)
- Module token в `Modules/Shedoy23.BannerlordLink/config.json` (gitignored)

**Logs:**
- Mod: `C:/Users/Edward/AppData/Roaming/Mount and Blade II Bannerlord/Logs/`
- Game: `C:/ProgramData/Mount and Blade II Bannerlord/logs/rgl_log_*.txt`
- Game crashes: `C:/ProgramData/Mount and Blade II Bannerlord/crashes/` (если user не cancel'ит dump)
- Backend: `ssh root@31.130.132.224 'supervisorctl tail -200 twitchbot stdout'`
- DB query: `sqlite3 /root/twitch-extension/backend/viewers.db 'SELECT ...'`

## Repo

- **GitHub:** `Shedoy23/shedstream` (private)
- **Files:** `BannerlordLink/` (mirror mod), `Расширение/backend/`,
  `Расширение/frontend/{viewer.js,extension.html,mobile.html,overlay.html}`,
  `Расширение/docs/BANNERLORD_*.md` + `CONTEXT_BANNERLORD.md`

## Recent gotchas / lessons

1. **Case-mismatch bugs тихие но дорогие** — backend хранит engine StringId
   lowercase, frontend hardcoded PascalCase, всё это время viewers платили
   крустики а UI показывал 0/10. Lesson: normalize at the boundary
   (5.27v approach). Опасно для любых dictionary lookups между Python и JS.
2. **TaleWorlds save format не backwards-compatible** — minor engine bump
   (1.3.15 → 1.4.5) crashes старые saves. Auto-update должен быть OFF
   на streaming PC.
3. **AddMember(-1) без re-attach даёт phantom** — Hero.PartyBelongedTo
   остаётся указывать на старую party, count=0 → MainParty в минус, passive
   heal ломается. Нужен EnterSettlementAction.ApplyForCharacterOnly как
   "home" target (BLT pattern).
4. **`isReinforcement: true` ignores initialPosition** — для placement near
   streamer нужно false + valid Vec3.
5. **Hideout (`MissionMode.Stealth`)** — 8-troop limit, position anchor
   опасен (может быть outside walkable area), enemy summon неуместен.
6. **Engine DLL lock при build** — если Bannerlord запущен, copy в bin/
   fails. Compile проходит (CS errors = 0), но DLL не обновляется.
   Решение: закрыть игру перед `dotnet build -c Release`.

---

**Использование для нового чата:** скинуть этот файл + сказать
*«Читай CONTEXT_BANNERLORD.md, продолжаем Bannerlord-модуль»*.
