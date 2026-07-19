# ARMY MVP — спека

Статус: **ПЕРВЫЙ СРЕЗ СДЕЛАН + ЗАДЕПЛОЕН 2026-06-14** (`feat(bannerlord): Army MVP first cut`).
`army_create`+`army_disband` (C# ArmyHandlers + backend whitelist/цены/manifest + фронт-слот).
Слот — **НИЖЕ** `bnr-party-orders-slot` (по просьбе владельца «чуть ниже приказов отряда»).
Статус армии в UI — из существующего `h.party_info.in_army` (без правки мода).

**2026-07-19 — FAST-FOLLOW СДЕЛАН (код), ждёт in-game verify + деплой:**
- Server-side гейты `hero.army_create` (kingdom + clan leader + not in army) до списания
  1000💎 — `handle_army_create_gate` в `bannerlord_party_orders.py`, вызов в оркестраторе
  кассы (`d056aa4`). Тест [8] в `test_bannerlord_buy_action.py`, 54/54 green.
- Cohesion-долив: `PartyOrderBehavior.TopUpViewerArmyCohesion` в hourly tick — армии
  viewer-героев держат cohesion=100 (`cad8684`).
- `HeroStateSync.BuildPartyInfo`: + `has_army`/`army_party_count`/`cohesion` (аддитивно;
  фронт прочитает ПОСЛЕ вердикта Twitch — до тех пор UI на `in_army`).
- DLL пересобрана (Release, 0 ошибок), в игру НЕ скопирована; бэк на прод НЕ задеплоен.

**Проверки пройдены:** мод билд 0 ошибок · бэк compile+тест 54/54+lint · фронт node-check.
**ОСТАЛОСЬ — проверка В ИГРЕ** (mod-код, авто-теста нет): чек-лист в CONTEXT_BANNERLORD.md
(§ Army in-game verify): собрать армию → приказы ведут → cohesion держится → роспуск → рефанды.

**ОСТАЛОСЬ ПОСЛЕ ВЕРДИКТА TWITCH:** UI состав армии + cohesion (фронт заморожен).

---
## Исходная спека (дизайн — для справки / расширения)

## Что строим
Зритель-лидер клана **в королевстве** собирает армию и командует ей. UI — слот **чуть выше
`bnr-party-orders-slot`** (приказов отряда). Приказы армии = **существующие «приказы отряда»**
(партия-лидер тащит армию за собой — НОВЫХ action-команд не надо).

## Решение по дизайну (важно — LGPL)
**Вариант A — армия КОРОЛЕВСТВА (vanilla `Kingdom.CreateArmy`), НЕ BLT-независимая армия.**
- Низкий LGPL-риск: vanilla TaleWorlds API, не изобретение BLT. БЛТ — только как идея, тела
  классов НЕ копировать. Короткие идиомы (выдать влияние → создать → откатить) — ок.
- Движок сам держит армию королевства (не рассыпается мгновенно как null-kingdom).
- Гейт «в королевстве» (вступление — уже есть action `hero.join_kingdom`).
- Вариант B (независимая армия, как BLT) — ОТКЛОН�ён: высокий LGPL-риск + нужна машинерия патчей.

**Twitch-compliance:** ок — тот же класс, что party orders (зритель платит криптики → влияет
на игру). Новых рисков нет.

## Проверенный vanilla API (1.2.x, по game-DLL)
- Создать: `hero.Clan.Kingdom.CreateArmy(hero, gatherSettlement, Army.ArmyTypes.Patrolling, partiesToCall)`.
  `partiesToCall` можно `null` (армия с одним лидером). `ArmyTypes`: `Besieger/Raider/Defender/Patrolling`.
- Влияние: vanilla CreateArmy списывает `Clan.Influence`. Перед вызовом выдать буфер
  `ChangeClanInfluenceAction.Apply(hero.Clan, 200f)`; snapshot влияния до бонуса; если
  `party.Army == null` после вызова — откатить влияние + `PostFailed("army_creation_failed")`.
  (Зритель платит криптики, поэтому влияние выдаём — криптик-цена и есть стоимость.)
- Успех детектится ТОЛЬКО постфактум: `hero.PartyBelongedTo.Army != null`.
- Распуск: `DisbandArmyAction.ApplyByUnknownReason(army)` (НЕ `party.Army = null` — грязно).
- Детект «зритель — лидер армии»: `mp.Army != null && mp.Army.LeaderParty == mp`.
- Перед CreateArmy: разблокировать AI у партий (`mp.Ai.SetDoNotMakeNewDecisions(false)`) — наш
  `PartyOrderBehavior.SetOrder` мог их залочить.

## Гейты (проверять server-side в бэке И в C#-моде)
`hero.PartyBelongedTo != null` (есть партия) · `PartyBelongedTo.LeaderHero == hero` · `Clan.Kingdom != null`
(в королевстве) · `Clan.Leader == hero` (лидер клана) · `PartyBelongedTo.Army == null` (нет своей армии) ·
`PartyBelongedTo.MapEvent == null` (не в бою) · `!IsDisbanding` · `!Clan.IsUnderMercenaryService` ·
`MemberRoster.TotalHealthyCount > 0` (есть войска). Фронт disable если не `is_clan_leader` + не в королевстве.

## Стабильность
Армию королевства движок держит, НО cohesion убывает. Для MVP — **ежечасный долив**
`army.Cohesion = 100f` в `PartyOrderBehavior.OnHourlyTickParty` (одна строка, без патчей). Полный
`BLT_ArmyDispersionPatch` на `Army.CheckArmyDispersion` — опционально, НЕ для MVP.

## 3 слоя (шаблон — party orders; mirror file:line)
**C# (`BannerlordLink/src/Actions/`):** новый `ArmyHandlers.cs` по образцу `PartyOrderHandlers.cs`
(ExecuteAsync → MainThreadDispatcher.Enqueue → Apply; `HeroLookup.FindByUsername`; `ActionFeedback.PostFailed`
на отказах, `GetActionId(data)`). Хендлеры: `CreateArmyHandler` (`hero.army_create`), `DisbandArmyHandler`
(`hero.army_disband`). + cohesion-долив в `PartyOrderBehavior` (там уже sticky party-orders + hourly tick).
+ армия-инфо в `HeroStateSync.cs` (`has_army`/`army_party_count`/`cohesion`) — как `at_war_names`, фронт покажет.

**Бэк (`Расширение/backend/`):** ветки `hero.army_create`/`hero.army_disband` по образцу
`bannerlord_party_orders.py` + интеграция в action-роут `routes/bannerlord.py` (~L2607 party-order). Цена:
`army_create` ~1000💎 (в `ACTION_PRICES_DEFAULT`), `army_disband` 0💎. Гейты server-side в `_prepare_action`
(в королевстве + лидер клана — есть данные из hero-state). Зарегистрировать оба в `_PURCHASABLE_ACTIONS`
+ `manifest.yaml` (modules/bannerlord). Backend-only? — нет, enqueue в мод (как party_order_set).

**Фронт (`viewer-bannerlord.js`):** слот `bnr-army-slot` ВЫШЕ `bnr-party-orders-slot` (~L4334). Рендер:
нет армии → кнопка «Собрать армию (1000💎)»; есть → состав (N партий) + cohesion + «Распустить» +
подпись «приказы ниже управляют армией». Грузить в clan-leader блоке (~L4456). Гейт: `is_clan_leader` И в королевстве.

## Объём
MVP = `army_create` + `army_disband` + переиспользование party-orders для команд + статус в UI.
Расширенный (потом): выбор партий, отдельные army-приказы с гейтами, anti-disperse патч.

## Шаблоны (file:line на момент 2026-06-14)
- C# party-order хендлер: `BannerlordLink/src/Actions/PartyOrderHandlers.cs`
- C# sticky behavior (+ hourly tick для cohesion): `PartyOrderBehavior` (ищи в `BannerlordLink/src`)
- Бэк party-order: `Расширение/backend/routes/bannerlord_party_orders.py` + ветка в `bannerlord.py` ~L2607
- Фронт party-order UI: `viewer-bannerlord.js` слот ~L4334, `loadBannerlordPartyOrders()` ~L1155
- Hero-state sync (куда класть army-инфо): `BannerlordLink/src/Util/HeroStateSync.cs`
