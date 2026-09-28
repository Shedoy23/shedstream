# Cross-review backend/connectors — независимая проверка

Дата: 2026-09-28. Проверены 10 кандидатов как гипотезы. Чужие JSON и runtime не изменялись. Ниже статические producer→consumer цепочки; живой сеанс/production и полная семантика внешних игровых сборок не проверялись. CodeGraph недоступен, использован targeted rg/read.

## Результат

- Confirmed: BE-020, BE-036, MOD-023, MOD-031.
- Qualified: BE-023, MOD-022, MOD-024, MOD-033, MOD-037, MOD-039.
- Полностью refuted findings: нет. Опровергнуты расширительные интерпретации: «research_unlocked уже врёт зрителю надписью», «свита — нативный game cap», «full desc теряется/нужно впервые добавить раскрытие», «manual paired override исправляет exported catalog».
- Наиболее важная дополнительная находка: manual PairedImplants override существует, но опубликованный is_paired берётся из другого вычислителя и настройку не использует.

## BE-020 — confirmed: имя клана используется как permission surrogate

Проверено:
- Расширение/backend/routes/bannerlord.py:2233–2246 — hero.create_clan читает cached clan_name; startswith("[BLink]") выдаёт «уже лидер».
- Там же:2259–2281 — hero.create_kingdom отказывает при отсутствии префикса.
- BannerlordLink/src/Actions/CreateClanHandler.cs:99–104 — создаваемый интеграцией клан действительно получает префикс. Это объясняет происхождение эвристики.
- Расширение/backend/modules/bannerlord/_adapter.py:2076–2088 — событие создания записывает clan_name; :2107–2118 — join_clan также обновляет имя. Имя описывает членство, не отдельный role.
- Frontend viewer-bannerlord.js:4798–4843 проверяет реальные info flags для ряда действий, но запрос всё равно попадает на backend gate по имени.

Попытка опровержения: это может быть намеренная политика «только интеграционные кланы». Однако ответ и комментарий называют именно лидерство; внешний native клан-лидер не может пройти, а простой участник префиксного клана совпадает с предикатом. Даже при желании такой product policy нужен отдельный managed_by_integration flag плюс real leader check.

Не доказано, что текущие игроки столкнулись с этим в проде. Статический ложный предикат подтверждён.

## BE-023 — qualified: дублирование авторской политики, а не нативный PartySize

Проверено:
- Backend bannerlord.py:1833–1883 — base cap 5, bonus из clan-upgrade effects, выбор add/upgrade по cached rows, min tier, стоимость, отказ по cached gold.
- BannerlordLink/src/Actions/RecruitTroopsHandler.cs:17–53 — это явно BLT-style авторская retinue: MAX_RETINUE=5, собственная TIER_COSTS, elite multiplier=3.
- Там же:116–147 — мод независимо считает cap=5+GetBonusFor и quote, :149–155 проверяет живой Hero.Gold. При upgrade использует живые CharacterObject.UpgradeTargets далее в handler.
- Frontend viewer-bannerlord.js:3923–4019 — третья копия вычислений, к которой добавлен собственный T5/T6 gate.

Коррекция: classification лучше duplicated_platform_policy / adapter-owned quote, а не утверждение что здесь украден нативный лимит отряда Bannerlord. Свита ShedLink имеет право на собственный баланс и 5 слотов. Ошибка архитектуры — несколько исполняемых копий и отказ до игры по cached данным. Передать разрешённый quote из owning implementation полезно, но нельзя молча заменить правило на native party capacity.

Риск divergence подтверждён; конкретный текущий числовой drift трёх таблиц данным review не доказан.

## BE-036 — confirmed: четвёртый module пропускается общим queued sweeper

Проверено:
- main.py:2091–2104 — цикл запускает отдельный legacy RimWorld sweeper и затем _expire_stale_queued.
- main.py:2117–2131 — SQL заранее ограничен тремя module_id, лишь потом вызывается get_module и adapter.handle_event(action.failed).
- modules/_base.py:168–193 — TTL failure общий контракт, но он не делает omitted module кандидатом SQL.
- Поиск остальных queued_ttl/_expire_stale_queued producer мест не обнаружил альтернативного generic обхода всех модулей.

Квалификация последствий: сегодняшние три игры покрыты этим IN; это blocker добавления четвёртой, не доказательство текущей потери средств. Новый адаптер теоретически может реализовать свой sweeper, но общий platform contract этого автоматически не обеспечивает. Refund ownership должен остаться backend, не игре.

## MOD-022 — qualified: эпоха является реальной deliberate policy, researched — плохое имя

Проверено:
- ShopManager.cs:57,110 — apparel/weapons реально фильтруются через IsThingResearched.
- :839–861 — реализация techLevel <= Faction.OfPlayer.def.techLevel, Undefined=false, fallback Industrial.
- :848–850 — комментарий прямо описывает ограничение магазина по эпохе. Это не случайно забытый IsFinished в этой ветке.
- :148 и :864–879 — recipes отдельно проверяют один researchPrerequisite.IsFinished, затем optional first product tech.
- :74,129,186,406 — surviving entries получают research_unlocked=true.
- Backend rimworld.py:1666–1684 сохраняет дополнительные поля через extra_json; frontend shop.js получает items, но literal lookup research_unlocked в актуальном frontend отсутствует.

Коррекция: намеренная политика «магазин не выше эпохи» сама по себе допустима. Подтверждён разрыв семантики поля research_unlocked и ограничение полноты каталога. Не подтверждено, что UI сейчас показывает «исследовано» по этому флагу либо что все предметы должны следовать native crafting research. Для 0.0.6 разделить catalog facts, technology policy и actual research requirements; policy решает владелец.

## MOD-023 — confirmed: recipe identity теряется до операции

Полная цепочка:
1. ShopManager.cs:136–188 перебирает recipes; каталог item identity — recipe.addsHediff.defName (:174), label — recipe.label; recipe ID не включён в payload. body_parts передаются labels, is_paired — boolean.
2. Frontend shop.js:248–307 выбирает максимум left/right.
3. Backend rimworld.py:2486–2540 находит catalog item и enqueue install_implant с def_name + part_hint, recipe/BodyPartRecord отсутствуют.
4. CommandFactory.cs:105 и PawnCommands.cs:158–174 ведут в PawnManager.InstallImplant.
5. PawnManager.cs:912–925 выбирает первый RecipeDef с matching addsHediff, затем только appliedOnFixedBodyParts[0]; :960–961 выполняет MakeHediff/AddHediff.

Попытка опровержения: это может быть намеренная мгновенная покупка, не хирургическая операция. Согласен: отсутствие surgery failure/doctor bill не должно автоматически считаться багом. Но два рецепта для одного hediff, race-specific applicability и custom Worker effects всё равно не различаются. «Любой recipe работает» этим контрактом не обеспечено; unsupported custom workers надо обозначать, не обещать вызов native surgery без отдельного решения.

## MOD-024 — qualified; дополнительно paired override не достигает экспорта

- ShopManager.cs:901–915 — Human body + первая applied fixed part, count>=2.
- Экспорт :185 прямо вызывает этот helper.
- PriceSettings.cs:121–157 содержит отдельный IsPaired/SetPaired и PairedImplants override.
- Поиск IsPaired потребителей в RimLink/Source нашёл UI настройки в RimLinkMod.cs:328.
- ShopManager.BuildCatalogWithPrices :351–372 использует IsEnabled/GetPrice, меняет copy["price"], не применяет Prices.IsPaired.

Следовательно, «есть manual override» — не mitigation exported is_paired в исследованном пути. Настройка может визуально поменяться в settings, но viewer получит прежнее вычисление по Human. Это дополнительное свидетельство рассинхрона двух implementations. При иной анатомии нужен конкретный список targets выбранной пешки; общий каталог может передавать только schema, не придумывать её тело.

## MOD-031 — confirmed: label-dedup удаляет разные valid defs

- EventManager.cs:431–447 — два HashSet: seenIds и seenLabels. Сначала IsValidIncident и prices.IsEnabled; далее разные defName с одинаковым непустым LabelCap получают continue.
- :476–486 — оставшийся entry получает исходный defName как id и fire_incident.
- SyncCatalogsInBackground (RimLinkGameComponent.cs:53–65) публикует именно этот список.
- Backend rimworld.py:2700–2716 сохраняет entries по ID; уже удалённый def не восстановится.
- Frontend viewer-rimworld.js:153–167,172+ рисует полученные события.

Намерение anti-duplicate явно написано в комментарии. Оно может быть полезной curated policy, но equality display label не доказывает равенство эффектов или ID. Коррекция продукта: группировать по label, позволять различить source/ID; не терять отдельный valid def молча. Про конкретную установленную collision evidence нет, scenario условный.

## MOD-033 — qualified: 4000/6000 действительно превращаются в 3000; не доказана числовая надпись зрителю

Цепочка подтверждена:
- EventManager.cs:463–474 присваивает T4=4000, T5=6000 в incidentParams.points; :481–482 cmd=fire_incident и params.
- Backend rimworld.py:2787–2799 читает сохранённые params и pending_cmd.update(params), сохраняя points.
- CommandFactory.cs:129 выбирает FireIncidentCommand.
- EventCommands.cs:258–268 читает top-level points и clamp до 3000; :272 ограничивает также default.
- Название safety cap в комментарии не отменяет рассогласование с producer.

Квалификация: frontend viewer-rimworld.js не показывает numeric threat points непосредственно. Поэтому формулировать «каталог содержит 4000/6000, executor применяет 3000», а не «зрителю обещано именно 6000». Сам cap допустим как safety/game-adapter policy. Надо синхронизировать effective parameters и cost tiers, а не автоматически снимать cap. Это текущая статическая разница, не live результат рейда.

## MOD-037 — qualified: lifecycle не имеет найденного research completion refresh

Проверены все literal references BuildCatalogWithPrices, BuildEventCatalog, SyncShopCatalog/Events, SyncCatalogsInBackground в RimLink/Source:
- RimLinkGameComponent.cs:71–106 initial/new-game session; guard _sessionInitialized; :113–114 delayed init.
- :39–68 строит и отправляет каталоги.
- RimLinkMod.cs:350 — UI catalog cache; :367–394 — UploadCatalog по кнопкам settings :130/231.
- :457–467 — UI event upload.
- Другого catalog rebuild по research completion в найденных references нет.

Пункт следует оставить ограниченным: исходники не содержат найденного автоматического refresh по такому событию, поэтому freshness нельзя гарантировать. Не объявлять любой heartbeat бессмысленным и не утверждать невозможность hot changes через внешние Harmony patches. User-triggered reupload существует; рестарт/загрузка сейва тоже обновляют. Catalog revision/freshness нужен, но все defs обычно не меняются в середине игры — особенно важны availability predicates, такие как research.

## MOD-039 — qualified INFO/P3; интерпретация «полный текст потерян» опровергнута

- ShopManager.cs:718/776/818 сокращает tooltip fragments.
- MakeItem :402 сохраняет отдельный desc; implant :176 берёт recipe.description либо hediff.description.
- Backend rimworld.py:1672–1679 сохраняет desc в description; :1792 возвращает description.
- Frontend shop.js:163–170 собирает description + tooltipText; :196 рендерит detailParts как полные параграфы в раскрытии.

Следовательно, рекомендация впервые добавить frontend раскрытие уже выполнена. Не вся метрика tooltip обязана присутствовать в desc (например derived effect details), поэтому blanket «ничего не теряется» тоже неверно. Оставить как ограничение tooltip/точечно проверить нужную отсутствующую информацию; отдельный high-priority generic migration здесь не обоснован.

## Проверки и ограничения выполнения

Read-only чтение/поиск по указанным исходникам. Runtime тесты игровых DLL не запускались, quoted hypotheses не приняты за authoritative результаты. Первая печать JSON через Python столкнулась с cp1251/UnicodeEncodeError; повторная печать с PYTHONIOENCODING=utf-8 показала корректные данные. Это не повреждение файлов. В report не добавлены внешние legal/compliance выводы.
