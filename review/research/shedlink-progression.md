# ShedLink: progression / equipment / achievements — инвентаризация к BLT-аудиту

База: `C:/Users/Edward/Desktop/work/.claude/worktrees/bannerlord-crash-analysis-a34de4`, ветка `claude/poststream-2026-09-22`, HEAD `0cdf6338db7bd1b5f5d9ab7e43b2b8b8efb31e30`. Чтение исходников, не доказательство живой игры. CodeGraph заблокирован; использованы текстовые поиски с последующим чтением конкретных путей. Все пути ниже относительно этой базы. Никаких runtime-изменений.

## 1. Два поколения build-системы, а не один список классов

**Новое:** создаваемому герою `AdoptHeroHandler.cs:301` вызывает `EquipmentShopBehavior.InitializeBuild`; save-owned `HeroBuildState` содержит specialization, выбранный тип оружейной способности, starter kit, общий cooldown. `Util/HeroBuildPolicy.cs:8–80` задаёт 4 специализации, 7 оружейных вариантов, ранги по навыку 50/150, обязательное экипированное/взятое в руку оружие, общий cooldown 90 секунд, длительность 45 секунд. Пассивы: guardian HP, assault melee damage, marksman ranged damage, mobility speed. Это реальные ограничения, а не только описания.

Полный путь: `frontend/viewer-bannerlord-builds.js:32–121` строит кнопки из build.specializations/power_options/starter_kits; `load():124–136` запрашивает `/api/bannerlord/build` → `routes/bannerlord.py:1648` берёт текущий inventory/build snapshot → `modules/bannerlord/builds.py:44–104` проверяет актуальный save/session/hero, выбранную способность и возможность управления → общий action API/transaction → `Actions/HeroBuildHandler.cs:27–91` снова проверяет живую игру, применяет выбор, выдаёт starter из реального каталога и отправляет applied + inventory/equipment/state. `Behaviors/EquipmentShopBehavior.cs:49–51` сохраняет JSON ledger через SyncData; `:260–267` отправляет `hero.inventory_snapshot` вместе с build. Игра вырабатывает availability/reason и actual skill rank (`Util/HeroBuildRuntime.cs:116–153`); Python накладывает авторизацию/цены/cooldown orchestration. Новый UI подключён из `viewer-bannerlord.js:458,479,3530,3605`.

**Старое:** `/classes` и `/class-state` (`routes/bannerlord.py:262–399`) читают DB `bannerlord_classes`, `bannerlord_hero_class`, `bannerlord_class_powers`; class level 1–3 пересчитывается из primary skill (50/150), не из старого class_level столбца. `HeroProfileBehavior.cs:47–51` сохраняет выбранный класс/стойку в save и восстанавливает backend через `hero.restore_profile:134`. Старые `hero.set_class`, `hero.reequip_gear`, `hero.upgrade_gear` отказывают для нового build (`SetClassHandler.cs:55`, `ReequipGearHandler.cs:51`, `UpgradeGearHandler.cs:74`). Поэтому сравнение BLT-классов должно явно назвать поколение героев, а не предлагать ещё один class picker.

**Граница:** новые способности/выборы runtime-owned, но определены нашим C# кодом, не универсальным capability API произвольного мода. Ни prestige reset, ни дерево многократных specialization unlocks в этих state/action paths не представлены. Это ограниченное отрицательное доказательство через рассмотренную модель и её действия, не вывод из отсутствующего слова.

## 2. Skills / focus / attributes уже есть и реально меняют HeroDeveloper

`viewer-bannerlord.js:1233–1242` посылает `hero.add_focus` / `hero.add_attribute`; `:4143–4147` — XP preset `hero.add_skill`. Общая касса `routes/bannerlord.py:1721`, `_charge_execute_enqueue:2803` валидирует цену, очередь, средства, cooldown, pending; собственно game state решает C#.

- `Actions/AddSkillXpHandler.cs:88–187`: целевой skill либо weighted random из DefaultSkills; class primary weight 12, other1. `:198–281`: cap330, native `HeroDeveloper.AddSkillXp(...isAffectedByFocusFactor:true)`, проверка before/after XP, развитие героя и `hero.skill_changed`. Targeted API существует глубже простой UI-кнопки случайного XP; поддержка custom SkillObject ограничена DefaultSkills reflection.
- `AddFocusHandler.cs:82–190`: MBObjectManager list SkillObject, заданный/случайный доступный skill, max5, tier cost game gold, `HeroDeveloper.AddFocus(checkUnspentFocusPoints:false)`, postcondition, event `hero.focus_changed`, full state.
- `AddAttributeHandler.cs:73–175`: аналогично CharacterAttribute, max10, native AddAttribute, Hero.Gold, event `hero.attribute_changed`, full state.
- Adapter `:507,557,561` маршрутизирует эти события в таблицы skills/attributes. `HeroStateSync.cs:142` строит полный `player.state_update`, `:91–108` отправляет подтверждаемый snapshot; `_adapter.py:1159` принимает и зеркалирует. UI отображает состояние через `/my-hero:1379`.

Нельзя предлагать «добавить focus/attributes/классовую прокачку» как отсутствующее. Потенциальный gap — depth после caps, runtime descriptors вместо vanilla списков, prerequisites/milestones; устанавливается только после BLT comparison.

## 3. Achievements существуют; lifetime — агрегат зрителя в текущей кампании, не биография героя

Живой router подключён `backend/main.py:141`; UI `_renderAchievementsInline` `viewer-bannerlord.js:4430–4480`, details во вкладке inventory `:5533–5539`, lazy load `:5664–5667`.

`routes/bannerlord_achievements.py:32–79` содержит **13** активных achievements: kills1/100/500/1000, tournament participation1, wins1/3, level10/20, gold500K/1M, созданный clan/kingdom. Family achievements в комментарии сняты, комментарий о неготовом family snapshot исторический и не доказывает сегодняшнее отсутствие family системы.

Путь: мод `KillRewardBehavior` ведёт mission-local BattleStats (`:349–355`), события `battle.stats_snapshot`; adapter `_on_battle_stats:2243`, финальные kills целиком `:2283–2298` → `increment_stat`; state update level/gold maxima `:1315–1321`; clan/kingdom creation flags `:2115,2182`; tournament joins/wins `:2412,2544`; `_check_unlocks:152–183` вставляет достижения, `:185–203` уведомляет чат, GET `:211–257` возвращает criteria/value/unlock/date.

**Не путать scope:** таблицы `m39_bannerlord_achievements.py:35–60` имеют channel_id+username(+stat_key/achievement_id), без hero_id, save_id, generation. При смене save reset идет через `routes/bannerlord_admin.py:61–62` RESETTABLE_TABLES и `_adapter.py:967–975`. Значит это cumulative viewer record внутри текущего набора кампании, может охватывать несколько поколений, но не настоящий бесконечный cross-save lifetime. GET отдаёт achievement rows, не весь произвольный stats ledger. Нет выделенной летописи жизни каждого героя в этой модели. Увеличение stats запланировано fire-and-forget из событий, не save-owned replayable biography. Живую надёжность/потерю событий этим чтением не подтверждаем.

## 4. Legacy уже частично есть

Нельзя утверждать «legacy полностью отсутствует». `AdoptHeroHandler.cs:245–268` регистрирует iteration в HeroIdentityBehavior и выдаёт `1000 + iteration*500` стартового золота. Это простой re-adopt bonus, а не prestige currency/rebirth skill tree. Семья/наследники/inheritance анализируются соседним исследованием и существенно сильнее одного этого бонуса. Полная prestige meta progression в рассмотренном build/action/state не установлена.

## 5. Equipment — настоящий динамический каталог, ownership, сундук и точные экземпляры

`EquipmentShopBehavior.cs:49–51` хранит ledgers в save. Runtime каталог из MBObjectManager; `:309–316` handshake → module.catalog_update → full inventories. `Util/EquipmentShopPolicy.cs:31–50` OwnedEquipment = OwnedId GUID, ItemId, ModifierId, Slot; EquipmentLedger = Build, Items, Revision. Это **существующая основа persistent item identity**, не нужно придумывать её с нуля. `Observe:55–75` сохраняет пропавший mod-content в storage, сохраняет ID при смене modifier на той же вещи; настоящая внешняя замена считается заменой instance. Нет creator/previousOwners/kills/history в этом ownership model.

Полный путь: `frontend/viewer-bannerlord-equipment.js` shop/inventory → `/api/bannerlord/equipment-shop` (`routes/bannerlord.py:1601`) → `modules/bannerlord/equipment_shop.py:35–98` current save/session/hero snapshot + pending guard → четыре actions `hero.buy_equipment/equip_owned/unequip_owned/discard_owned` → `Actions/EquipmentShopHandlers.cs:27–239`. Мод заново проверяет MBObjectManager item, sellable, level, price, native slot/harness compatibility, owner, modifier, Mission/Prisoner/session; списывает **Hero.Gold**, меняет EquipmentElement / roster / ledger, проверяет эффект, applied, inventory/equipment/full-state sync. `:105–115`: покупка в личный сундук, не party loot (который vanilla может продать в городе); `:180–228`: снятое тоже в сундук. Capacity10 — наша политика. `:73–101` direct-equip trade-in при соответствующем режиме — обмен старого на новый у системы, **не viewer marketplace**.

Backend сохраняет projection и авторизует; **часть shop gating всё ещё дублирует game policy**: tier→level в `equipment_shop.py:5`, это вопрос предыдущего hardcode audit. Frontend представляет возможности, но не весь модовый набор характеристик.

## 6. Reforge — реальная гарантия следующего качества, не персональная ковка

`viewer-bannerlord.js:4342–4418` «Кузница» → `hero.reforge_quality`; transaction `bannerlord.py:2923–2928,3065–3066` → `modules/bannerlord/reforge.py:4–35`: выбирает следующую из game-provided `reforge_options`, держит paid right pending/active по channel/save/hero/user/slot/item. Мод `ReforgeQualityHandler.cs:63–132` сверяет expected item+modifier+session, получает ItemModifierGroup, GetModifiersBasedOnQuality, выбирает next Fine/Masterwork/Legendary и присваивает EquipmentElement(item,nextMod), проверяет, applied и snapshots. Не генерирует новый ItemObject, имя или craft design.

`ReforgeRightsBehavior.cs:11–19` намеренно **без SyncData**: оплаченные права берёт из backend, восстанавливает после отката сейва; права не тождественны наблюдаемому состоянию экипировки. Не переносить механически BLT save-owned платежи поверх этой границы.

## 7. Старые trophy/smith/auction — не завершённые активные mechanics

Проверено не только наличие файлов, но wiring:

- `backend/main.py:142–154` отключены router custom-items и auctions; `:2383–2384` отключён auction resolver.
- `routes/bannerlord.py:988–994` `hero.smith_item` и `hero.equip_trophy` отсутствуют в purchasable allowlist; активна reforge. Оставшиеся ветви `_charge_execute_enqueue:3081` и trophy validation `:2489` не делают их доступными viewer API.
- `routes/bannerlord_custom_items.py` по-прежнему имеет generator, rarity/stat/name tables и legacy inventory GET, но не подключён. Турнирная генерация убрана (adapter `:2575`, comments custom_items), потому нельзя считать trophy drops сегодняшней наградой.
- `Actions/EquipTrophyHandler.cs:17–31,240` подбирал существующий ItemObject по типу/тиру, имя было backend trophy label; `Net/ActiveTrophyState.cs:33` process-memory bonuses + `Patches/DamageHookPatch.cs:494` накладывает damage/armor. Регистрация handler (`ActionRegistry.cs:70`) не отменяет API gate. Не считать доказанной активной ковкой персонального предмета.
- Аукционский Python resolver переписывает DB owner и платит seller; он не является game-authoritative передачей OwnedEquipment. Исторический scaffold нельзя автоматически воскресить как готовый рынок.

**Точный gap:** авторская ковка нового дизайна/модификатора, item biography, viewer-owned transfer/auction не установлены в активном authoritative equipment flow. Но persistent exact instances, modifiers, chest и paid reforge уже есть.

## 8. Economy boundary для будущего сравнения

Крустики = platform entitlement; Hero.Gold = настоящие динары. Buy action имеет server transaction + delivery result/refund; игровые Gold deductions проверяет мод (EquipmentShopHandler и HeroGoldCharge). Achievements сейчас informational unlock + chat, не выдача нового ItemObject. Legacy1000+iteration500 — game gold. Платформенный аукционский scaffold запрещено переносить из-за отсутствия игрового delivery path и старого выключенного решения; свежие Twitch юридические выводы этот документ не делает.

## Что уже нельзя снова предлагать как новую систему

Skills/focus/attributes, runtime-ranked weapon powers, build specialization, free starter kit, exact owned item GUID/quality, личный сундук, native modifier reforge, 13 Bannerlord achievements, user aggregate kills/tournaments/level/gold, iteration starting-gold bonus. Однако 13 achievements не равны полной hero lifetime statistics; OwnedId не равен истории вещи; reforge не равно smithing дизайна.
