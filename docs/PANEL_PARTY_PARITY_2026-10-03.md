# Панель Preact: свита, затем клан/отряд/армия

## Замороженный срез A: вся карточка «Свита»

Исходники `3f67c38`, финальные проверки `f593be3`. Реализована вся видимая карточка перед развитием героя: состав/тир/элита, серверный лимит, basic/elite найм либо upgrade, массовая тренировка с приблизительной ценой, золото, общий серверный cooldown найма, отдельный cooldown тренировки, раскрытие и телеметрия. Production entrypoint использует её через настоящий PanelApp/HeroDevelopmentView; отдельного bodyguard-функционала нет.

### Контракт и доказательства

- Эталон — текущие неизменённые 23 скрипта `Расширение/frontend/` в настоящем jsdom/VM; добавлен только выбранный host `bnr-retinue-slot`. Полный chronological trace содержит метод/path/query/body/JWT/cache, shell stats/level/duels, action tail 3500 ms, скрытую страницу, оборудование, боевые и общие polls, usage. Не фильтруем записи. Нормализация только случайных action/batch ID
- `test/panel-fixtures/generate-party-responses.py` вызывает настоящие наружные HTTP handlers на временной SQLite с полными миграциями; `RIMWORLD_PRICES_PATH` задан до imports. 63 формы ответов для A/B и будущего отдельного вассального среза. `fixture_*` — явно засеянные локальные идентичности, не данные текущей игры. Наличие заготовок вассалов не означает реализованного UI
- Сначала `857e3e7`: новые DOM/parity тесты красные, 16 failed/1 passed, отсутствующие controls. `f6913f4`: дополнительный red stale-handler test действительно отправлял лишний POST. После реализации: 32 focused tests зелёные
- По одному controlled mutation на каждое request family: инверсия `is_elite`, неверный action type тренировки. Также снятие stale hero-context guard. Каждый exit 1; byte-exact восстановление собственного backup, одинаковый SHA256; после восстановления общий прогон зелёный
- Все unit/DOM: **506 passed**, 2 opt-in HTTP skipped; отдельный свежий изолированный real HTTP: **2 passed**. Typecheck, build и check-build exit 0. `minify:false`, source maps/readable Preact/licenses сохранены
- `measure-build.mjs`, gzip -9 каждого файла отдельно: panel-mobile initial **157264 raw / 44018 gzip bytes**. Это import closure с HTML/CSS/JS без внешнего Twitch Helper, HTTP responses и sourcemaps. Полный список файлов в evidence

### Намеренные безопасные отличия

1. Пустая свита при gold 0→500000 больше не остаётся неактивной. Старый renderer кешировал только `retinue:[]`; новый вывод зависит также от gold/cap/config. Отдельный тест оставляет старый oracle красным именно по исправляемому поведению, HTTP parity проверяется независимо
2. Без серверных цен/множителя или лимита действия недоступны, есть «Обновить цены свиты» с настоящим no-store config GET. Нет подстановки пяти слотов либо бесплатной цены. У legacy оставались fallback numbers
3. Старые обработчики не отправляют действие после наблюдаемой смены героя/личности или остановки. Общий unknown-outcome transport lock сохранён; обычное обновление JWT не ломает живую кнопку. Generic action JWT guard исправлен отдельно родительским checkpoint `fc0dde7`
4. Cooldown refusal карточки показывается на кнопке серверными секундами, без повторного toast, как у legacy. Не подменяем queue-success игровым применением

### Неизменённые ограничения server contract

Максимумы basic tier 5 / elite tier 6 и расчёт приблизительной тренировки унаследованы от старого UI, а не выданы за серверные authoritative quotes. API не экспортирует `can_recruit/can_train/max_tier` или точные UpgradeTargets. Их проверяет игра; её поведение не доказано этими тестами. Цены и cap берём только из ответа. Возвраты/поздние отказы остаются общим механизмом панели.

## Срез B: ещё не завершён в этом checkpoint

Следующий полный блок: clanless create/join, member/leader leave с подтверждением, создание отряда, все шесть стратегических приказов с editor/release и армия create/disband. Семья, наследование, вассалы, королевство, дипломатия, кузница и остальные dynasty-карточки сюда не входят. Полуработающие соседние карточки не монтируем.

## Границы проверки и среда

- Документальный поиск: `docs-search.py свита` подтвердил перенос карточки перед progression; `party orders` нашёл `Расширение/docs/ARMY_MVP_SPEC.md`. Историческая спека имеет устаревшие строки про порядок карточек; реальный текущий frontend — oracle
- Browser loopback запрещён, desktop offline: визуальный проход 318 px/телефон/Hosted Test Twitch не выполнялся. Никаких обходов запрета. DOM/HTTP не называем живой игрой
- Первый HTTP запуск отдельным exec не видел loopback server другого exec (ECONNREFUSED); свежий server+tests в одном shell прошёл. Это проверка HTTP CLI, не обход браузерного ограничения
- Legacy frontend/backend (включая их тесты), моды, OBS и frozen ZIP не менялись. GitHub writes/CI, merge/deploy/Twitch/game actions не выполнялись
- [Сохранённые логи, размеры и мутации](evidence/panel-party-2026-10-03/) относятся к A; следующие результаты B будут отмечены отдельно
