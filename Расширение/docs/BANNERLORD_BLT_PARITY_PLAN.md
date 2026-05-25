# Bannerlord BLT-Parity Improvement Plan

**Создан:** 2026-05-25 после полного аудита BLT vs нашего мода.
**Базовый референс:** `billw2012/Bannerlord-Twitch` (master branch).
**Наша точка входа:** `X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\Modules\Shedoy23.BannerlordLink\src\`.

Аудит выявил **где мы впереди BLT** (clan/kingdom/multi-tenant) и **где BLT впереди** (engagement loop: progression-feel, custom items, achievements). Этот документ — roadmap для closing'а второго gap'а.

---

## Где мы УЖЕ впереди BLT (не трогаем)

- Full **Clan / Kingdom** system (create/join/leave). У BLT — stub.
- **Multi-tenant backend** — мы платформа для N стримеров, BLT — per-streamer install.
- **Position override на summon** (perpendicular/front-of-streamer).
- **Twitch Extension overlay UI** — у BLT только OBS browser source HUD.
- **Clan upgrades models** (party_size/speed bonuses).
- **`IsSideDepleted` Harmony patch** — BLT этого не имеет.

---

## TOP-10 Priority List (по убыванию impact / effort ratio)

### ★★★ 1. Name markers `@username` над agent'ами

**Зачем:** стример играет в slop-mode — не видит кто за него, кто против. Hover-only.

**Подход:**
- Harmony postfix на `MissionNameMarkerTargetVM` ctor — заменять name на `@username` если agent имеет `[BLink]` префикс.
- Harmony postfix на `NameMarkerScreenWidget.OnLateUpdate` — keep markers visible во весь bой.
- Reuse наш `Util/HeroNaming.ExtractUsername` для name parsing.

**Effort:** medium (1-2 файла в Patches/, ~80 строк).
**Файлы:** `src/Patches/NameMarkerPatch.cs` (новый).
**Тест:** виден ли `@kuro_gothic` над agent'ом в field battle.

---

### ★★★ 2. Per-user cooldowns вместо per-channel

**Зачем:** сейчас один viewer купил heal → все viewers ждут CD. Unfair → меньше engagement.

**Подход:**
- Backend: change cooldown key from `(channel_id, action_type)` → `(channel_id, username, action_type)`.
- Migration: `bannerlord_cooldowns` table или JSON column — добавить `username` к индексу.
- Frontend: pass `username` в `/api/bannerlord/cooldowns` query.

**Effort:** medium (~150 строк, backend + migration + frontend).
**Файлы:** `backend/routes/bannerlord.py`, новая migration `m38_per_user_cooldowns.py`.
**Тест:** два viewer'а одновременно покупают heal → второй не получает «cooldown active».

---

### ★★★ 3. Refund крустиков на отказ мода

**Зачем:** backend списывает крустики оптимистично ДО отправки action в мод. Мод отказывает (mission state / dead hero / not enough Hero.Gold) — крустики потеряны навсегда. Viewer frustration → churn.

**Подход:**
- Backend `bannerlord_actions` row уже хранит status. Когда mod пушит `action.failed` event с action_id — backend проверяет status, делает refund крустиков на `crustic_balance`.
- Mod: ensure все handlers пушат `action.failed` (сейчас многие просто `Log` и `return`).
- Atomic refund через DB transaction (SELECT current_balance + UPDATE + INSERT в audit log).

**Effort:** medium (~200 строк, mod + backend).
**Файлы:** `backend/routes/module_api.py` (action.failed handler), все Handlers в моде (push failed event).
**Тест:** viewer покупает add_attribute во время Mission → mod отказывает → крустики возвращаются.

---

### ★★★ 4. Class-weighted XP

**Зачем:** cavalry-класс должен получать больше Riding/Polearm XP, не random. Сейчас Berserk получает Crossbow XP с тем же шансом что и One-Handed. Progression feels random → demotivating.

**Подход:**
- В `AddSkillXpHandler.Apply()` (mod) — добавить weight'ы для skill pick:
  - Class skills (от `PowerCache.GetHeroClass(username).classKey` → skill list) × 15
  - Equipment-related skills (от current loadout) × 4
  - Other × 1
- Mapping `classKey → primary skills` (cavalry → Riding+Polearm+OneHanded+Bow, archer → Bow+Throwing+Tactics, etc.) — копируем из BLT `ImproveAdoptedHero.cs` matrix.

**Effort:** low (~60 строк, один файл).
**Файлы:** `src/Actions/AddSkillXpHandler.cs`, добавить mapping const'у.
**Тест:** viewer cavalry-класса получает Riding XP ≥ 60% случаев, не random 1/24.

---

### ★★★ 5. Achievements + chat announce

**Зачем:** «Slay 100 enemies as Archer», «Win 5 tournaments» — Twitch chat reaction. Goal-driven engagement.

**Подход:**
- Backend new table `bannerlord_achievements`:
  - `username, achievement_id, unlocked_at, channel_id`
- `bannerlord_user_stats` table extension (или derive from existing event stream): `total_kills`, `tournament_wins`, `level`, `kills_per_class`.
- Mod пушит events: `kill.recorded`, `tournament.won`, `level.reached` — уже есть, нужно агрегировать в stats.
- Backend periodic check (raised on event): сравнить counts с `ACHIEVEMENT_DEFINITIONS` → unlock + push `achievement_unlocked` event → bot announce'ит в Twitch chat через chat-bot.
- Frontend: показать achievements list в viewer profile modal (extension.html).

**Effort:** high (full feature — ~400-500 строк, migration + backend logic + frontend UI).
**Файлы:**
- `backend/migrations/m38_bannerlord_achievements.py`
- `backend/routes/bannerlord.py` (achievement evaluator)
- `frontend/viewer.js` (UI)
- Mod: возможно дополнить existing events.
**Тест:** kill 100 врагов → unlock notification в chat → запись в profile UI.

---

### ★★★ 6. Custom items + Smith + Auction

**Зачем:** единственная BLT-фича где viewer получает persistent уникальный artifact с именем. У нас всё equipment ephemeral (рерол'ится). Smith «Эспада Жнеца Кости +12 Damage» — viewer ценит, аукционит — retention killer.

**Подход:**
- Backend table `bannerlord_custom_items`:
  - `id, owner_username, channel_id, name, base_item_id, modifier_json, created_at`
- Mod handler `hero.smith_item` — crafts CharacterObject с RandomItemModifier + persisted reference на backend.
- Mod handler `hero.auction_item` — opens chat auction с reserve + countdown (5 минут).
- Frontend: viewer profile показывает inventory custom items.

**Effort:** high (~600-800 строк, multi-system feature, M40+ migration).
**Файлы:**
- `backend/migrations/m40_custom_items.py`
- `backend/routes/bannerlord.py` (auction state machine)
- `src/Actions/SmithItemHandler.cs`, `src/Actions/AuctionItemHandler.cs`, `src/Actions/BidOnItemHandler.cs`
- `src/Util/CustomItemRegistry.cs`
- `frontend/viewer.js` (inventory + bid UI)
**Тест:** viewer кует меч с именем «Жнец» → видит его в profile → выставляет на аукцион → другой viewer перебивает → owner change persists в save.

---

### ★★ 7. Succession / heir on death

**Зачем:** если viewer умер — accountов permanent dead. Жёстко для retention.

**Подход:**
- Backend `bannerlord_heroes`:
  - Add column `iteration INT DEFAULT 1`.
- При `HeroKilledEvent` для adopted hero — backend увеличивает iteration, отмечает heir candidate.
- Next time viewer чатит / opens extension — auto-adopt новый wanderer от того же username.
- Сохранить `family_name` / clan affiliation для continuity.

**Effort:** medium (~150 строк).
**Файлы:**
- `backend/migrations/m39_hero_iteration.py`
- `backend/routes/bannerlord.py` (adopt handler reads iteration)
- `src/Behaviors/MainCampaignBehavior.cs` (HeroKilledEvent integration)
**Тест:** kill viewer's hero → viewer пишет в chat → автоматически новый hero с тем же username.

---

### ★★ 8. In-game popup + alert sound

**Зачем:** стример не знает что viewer присоединился к бою. Хочется audio cue.

**Подход:**
- Mod: добавить `InformationManager.DisplayMessage(new InformationMessage(...))` в `SummonHeroHandler` после успешного spawn.
- Audio: `SoundEvent.CreateEventFromString("event:/ui/notification/quest_finished")` или похожий vanilla SFX.
- Kill streak popup: `BLTAdoptAHeroCommonMissionBehavior.ShowKillStreakPopup` копируем — visual + sound при 5/10/15.

**Effort:** low (~50 строк).
**Файлы:** `src/Actions/SummonHeroHandler.cs`, `src/Behaviors/KillRewardBehavior.cs`.
**Тест:** summon viewer → попап + звук в игре.

---

### ★★ 9. Sub multiplier на gold/XP

**Зачем:** Twitch sub'ы получают bonus → loyalty mechanic + monetization.

**Подход:**
- Twitch JWT уже содержит `role: subscriber | viewer`. Mod получает в action data.
- Backend route handler парсит JWT → ставит `data["sub_boost"] = 1.5` (или 2× per tier) если sub.
- Mod handlers: при apply gold/XP — умножает на `sub_boost`.
- Streamer-config'able multiplier через admin panel: `SUB_BOOST_TIER1`, `SUB_BOOST_TIER2`, `SUB_BOOST_TIER3`.

**Effort:** low (~80 строк, backend + 5-7 handlers).
**Файлы:** `backend/routes/bannerlord.py`, multiple Action handlers.
**Тест:** sub viewer добавляет gold → получает 1.5×.

---

### ★★ 10. Tournament anti-snowball debuff

**Зачем:** один viewer выигрывает 10 турниров подряд — boring.

**Подход:**
- Backend track `last_5_winners` per channel.
- При `tournament.started` — для каждого в queue, если он среди last 5 — temp skill cut 20% (мод применяет при OnAgentBuild через `_skillModifier`).
- Reset после participation.

**Effort:** low (~100 строк).
**Файлы:**
- `backend/routes/bannerlord.py` (winner history tracker)
- `src/Behaviors/TournamentMissionBehavior.cs` (apply temp debuff)
**Тест:** 5× выигрыш → 6-й турнир тот же viewer проигрывает раньше.

---

## Reference: фичи которые БЫЛИ кратко обсуждены но НЕ внедряем

- **Hot-modify Hero attributes во время Mission** → defer queue вместо block (TODO позже, не критично — сейчас skip + log)
- **Diplomatic actions** (declare war/peace) — engine ненадёжен, риск краша. Отложить пока.
- **Spectator vote during fight** — не в BLT, не делаем
- **AI advisor** — отдельный sprint, не parity feature

---

## Sequencing рекомендация

**Sprint 5.29:** #1 (Name markers) + #4 (Class XP) + #8 (Popups) — quick wins, low risk.
**Sprint 5.30:** #2 (Per-user cooldowns) + #3 (Refund) — backend rework, тестировать раздельно.
**Sprint 5.31:** #7 (Succession) + #9 (Sub multiplier) — backend continuation.
**Sprint 5.32+:** #5 (Achievements) — большой feature, отдельный sprint.
**Sprint 5.33+:** #6 (Custom items) — самый большой, требует серьёзный design.
**Sprint позже:** #10 (Anti-snowball) — quality-of-life, не критично.

---

## Файловая карта BLT (для дальнейшего research)

Когда понадобятся implementation details:

| BLT-фича | Файл (relative to BannerlordTwitch/) |
|---|---|
| Adopt logic | `BLTAdoptAHero/Actions/AdoptAHero.cs` |
| Class-weighted XP | `BLTAdoptAHero/Actions/ImproveAdoptedHero.cs`, `SkillXP.cs` |
| Name markers | `BLTAdoptAHero/UI/MissionNameMarkerUIHandler.cs` |
| Achievements | `BLTAdoptAHero/Achievements/` (entire folder) |
| Custom items | `BLTAdoptAHero/CustomItems/`, `Actions/SmithItem.cs`, `AuctionItem.cs` |
| Hero powers | `BLTAdoptAHero/Powers/` |
| Tournament queue | `BLTAdoptAHero/Behaviors/BLTTournamentQueueBehavior.cs` |
| Anti-snowball | `BLTAdoptAHero/Behaviors/BLTTournamentSkillAdjustBehavior.cs` |
| Summon | `BLTAdoptAHero/Actions/SummonHero.cs`, `Behaviors/BLTSummonBehavior.cs` |
| Sub boost | `BLTAdoptAHero/GlobalCommonConfig.cs` |

Raw URL pattern для research:
```
https://raw.githubusercontent.com/billw2012/Bannerlord-Twitch/master/BannerlordTwitch/BLTAdoptAHero/<path>
```

---

## Когда возвращаемся к этой работе

1. Прочитай этот файл → context loaded.
2. Выбрать sprint из sequencing.
3. Спросить юзера: «начинаем с #1 (Name markers)?»
4. Reuse research agent для углублённого BLT-code review если нужны точные implementation details (sub-agent типа research — см. `CONTEXT.md`).

См. также:
- `CONTEXT_BANNERLORD.md` — main handoff (sprint state, deploy инфра)
- `CONTEXT.md` — main extension context (multi-tenant infra)
