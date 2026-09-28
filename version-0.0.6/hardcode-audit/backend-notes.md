# Backend: аудит игровых hardcode в копии 0.0.6

Аудит read-only runtime. Изменены только материалы `version-0.0.6/hardcode-audit`. Production, live DB, конфиги, игра, исходники backend не менялись. `active` ниже означает достижимый путь по исходникам, а не подтверждённое использование текущим каналом.

## Результат

43 группы в `backend.json`. Это не 43 бага: включены правильные платформенные ограничения, существующие динамические пути и отключённые механики, чтобы следующий этап не удалил их ошибочно. Классификация: {'game_truth': 8, 'adapter_constraint': 21, 'duplicated_platform_policy': 9, 'platform_policy_ok': 4, 'legacy_inactive': 1}.

Первые практические блокеры:

1. BE-018: шесть культур Bannerlord проверяются до постановки создания героя в очередь. Runtime culture с новым ID не пройдёт.
2. BE-020: лидер клана определяется по префиксу `[BLink]` в имени. Создание королевства отвергает клан без префикса независимо от реального leader state.
3. BE-008: RimWorld теряет label/metadata навыка при записи snapshot, затем выдаёт одно из 12 vanilla названий либо raw ID.
4. BE-001/002/004: ShedColony держит закрытые товары и профессии. Игра сообщает лишь отсутствующие серверные товары; добавить новую вещь своим каталогом не может.
5. BE-017/027: Module API capability welcome отражает server manifest; новые типы catalog и event требуют правки сервера. Это пока протокол адаптеров, не discovery запущенной сборки.
6. BE-021/023: авторские BannerLink/ShedLink динаровые costs, retinue cap и upgrade prechecks повторены в backend. Это duplicated_platform_policy, не доказательство native engine цены или PartySize. Требуется единый владелец правил и свежий quote, без молчаливой замены авторской механики ванильной.
7. BE-036: TTL sweeper перечисляет три module_id. Четвёртая игра не попадёт в этот путь expiration/refund без правки core.

## Доказательный вертикальный пример: equipment requirements

`module.catalog_update` → Bannerlord adapter → `equipment_shop.store_catalog` → `module_catalogs` → `/api/bannerlord/equipment-shop` → `buy_reason` и `viewer-bannerlord-equipment.js`.

- Store принимает только tier 1..6.
- После `**entry` перезаписывает `required_level` по backend `TIER_LEVELS`.
- API использует сохранённое значение для `can_buy/reason`, клиент рисует его как уровень.
- При покупке тот же validator проверяет его вновь, чужой client override не помогает — это правильно для security.

`python version-0.0.6/hardcode-audit/backend-probe.py` воспроизводит реальными функциями на SQLite `:memory:`. Exit 0, лог `backend-probe.log`: синтетический tier4 required_level1 становится25; герой уровня24 получает `level_locked`; синтетический tier7 не сохраняется.

Ограничение вывода: текущий C# publisher уже нормализует public tiers в1..6; таблица levels сейчас согласована с backend. Probe доказывает закрытую границу и механизм будущего дрейфа, НЕ live пропажу конкретной модовой вещи. Сам gate уровней — авторская policy ShedLink (BE-035 `duplicated_platform_policy`), а не native item requirement. Его нельзя молча удалить под лозунгом game truth.

## Что уже динамическое и что сохранять

- Bannerlord settlements приходят от игры. Новый equipment/inventory и build хранят runtime descriptors, slots, specialization/starter options. Для дальнейшей миграции это полезные рабочие образцы.
- RimWorld shop и event entries уже приходят из игры, с произвольными item IDs. Проблемы дальше: category dispatch, metadata projection, split storage и price ownership.
- ShedColony хранит полный `colonist.state` и `colony.targets`, включая здания/исследования. Jobs capacity принимает произвольные ключи, но assign_job позже применяет whitelist.
- `KNOWN_SKILLS` и `KNOWN_ATTRIBUTES` Bannerlord НЕ текущие белые списки: новые ключи допустимого формата идут в мод.
- Backend law handler НЕ содержит закрытого списка законов. Его metadata/quote ещё нужно связать с game catalog; hardcoded UI laws — отдельная frontend находка.
- Backend family берёт взрослых наследников из игровых heir events/state; комментарий `>18` не доказывает backend age calculation.
- RimWorld server blocklist существует; старый текст MOD_COMPAT_AUDIT об отсутствии blocklist больше не истина. Он полезен как аварийное снятие проблемного товара. Тест blocklist выполнен координатором отдельно.

## Не смешивать отключённую и действующую кузницу

`hero.smith_item` / `hero.equip_trophy`, old custom-item rarity generator, auction routers и tribute boost отключены для viewer purchase. Но `hero.reforge_quality` — отдельная действующая механика: backend allowlist строка980, frontend вызывает её в строке4417. Поэтому BE-032 не опровергает frontend FE-008 о фиксированной лестнице качества действующей кузницы.

Старые class/upgrade gear действия являются compatibility path: при equipment_session backend их блокирует. Нельзя объявлять их безусловно активным основным интерфейсом 0.0.6.

## Границы authority

Игра сообщает существующие ID, названия, состояния, native требования, допустимые игровые переходы и итог исполнения. Backend сохраняет Twitch identity, channel isolation, viewer ownership, разрешённые предложения, крустиковые цены/ledger/refund и compliance. Клиент не может диктовать цену, владельца, величину награды или лимит детей.

Если game cost относится к Hero.Gold, предпочтителен game quote с version/state freshness. Если cap принадлежит продукту (5 детей,3 мастерские,2 каравана,1..16 stacks), его надо именовать отдельной policy, не выдавать за физическое ограничение игры. При переносе нельзя потерять anti-spam и policy checks.

## Охват и честные ограничения

- 82 Python-файла backend вне tests/migrations разобраны AST для поиска крупных literal containers; это обзор кандидатов, не доказательство всех ветвей.
- 38 файлов в `reviewed_files`: focused чтение sections/call paths; включая manifests/refusals, ancillary BL routes, schema helpers, M35 seed и equipment test fixture. Список `scanned_files` отдельно.
- Runtime routes подтверждены `main.py`: RimWorld строка70, Module API126, Bannerlord138, ShedColony139, ancillary154–162.
- Миграционные seeds не являются доказательством actual production DB catalog. После migrations данные могли меняться.
- Содержание внешнего Java connector ShedColony, реальные модовые сборки, свежие game logs и prod storage не проверялись этим аудитом.
- Manager registry/routes и backend templates распределены координатором в другие части аудита. Не заявляю их полностью проверенными здесь.
- Pets/собственные guild/loyalty/TTS/платформенные quests — авторский контент платформы, не справочники из запущенной игры. AST scan не превращает их constants в дефекты game truth.
- Bannerlord admin reset table lists — schema authority; это не каталог игровых сущностей.

Перед implementation: выбрать пару вертикальных slices (cultures/laws и RimWorld skill descriptors), добавить schema/version/freshness/empty-vs-unknown, пройти путь игра→хранение→UI→action quote→game result. Не переименовывать все constants и не разрешать произвольное выполнение из manifest.

## Поправка независимого cross-review

BE-021 и BE-023 классифицированы как `duplicated_platform_policy`: цены семейных/организационных операций и BLT-style свита являются авторскими правилами BannerLink/ShedLink. Аудит выявляет их ручное зеркалирование и риск дрейфа/устаревшего quote, а не требует заменить их native моделями движка. Backend identity и ownership остаются обязательными.
