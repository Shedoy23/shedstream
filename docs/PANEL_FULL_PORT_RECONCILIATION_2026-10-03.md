# Повторная сверка кнопок с исходной инвентаризацией

Это актуальное дополнение к четырём историческим `full-port-inventory-*.md`.
Их отметки «нет / gap» описывают базу b2064f4. Текущая таблица разделов,
parity, мутаций и снимков: [PANEL_FULL_PORT_COVERAGE_2026-10-03.md](PANEL_FULL_PORT_COVERAGE_2026-10-03.md).

## Bannerlord

| Старые кнопки и локальные элементы | Новый компонент / состояние |
|---|---|
| Турнир: вступить, прогноз на показанного участника, отменить | TournamentPanel; реальные queue/round/participants, смена раунда отменяет consent |
| Герой: культура, случайная культура, создать/возродиться | HeroLifecycleView; cultures из content-catalogs, предупреждение о новом герое |
| Ежедневная награда: динары / XP | DailyView; суммы daily-status |
| Мужской / женский пол | HeroProfileView; config quote и подтверждение |
| Личный NPC-брак, развод, ребёнок, дерево семьи | HeroProfileView; состояние героя и ответы игры |
| Каждый фокус/атрибут, покупка опыта, класс | ProgressionView/HeroDevelopmentView; игровая progression, группировка навыков; custom IDs не теряются |
| Пресеты динаров, персональный XP, необязательный каталог | ShopView; цены и action IDs API |
| Прежние upgrade/reequip, discard надетой вещи | LegacyGearView/LegacyInventoryView; при новом equipment_shop_ready старые controls скрыты как раньше |
| Новый магазин/инвентарь, фильтры/детали, купить/надеть/снять/выбросить | EquipmentView; сохранён прежний Preact перенос и guards |
| Кузница: раскрыть, выбрать вещь, перековать | ForgeView; expected_item_id сохранён |
| Боевые секции/настройки/стойки, призыв сторон, способности/оружие | CombatView; server UI order, цены/статус/cooldown |
| Свита: нанять/прокачать basic/elite, тренировать войска | RetinueView; сохранён прежний перенос |
| Клан: создать/имя, вступить/поиск, выйти, отряд создать | PartyView; прежние сценарии и full dynasty host |
| Приказы отряда: тип, цель/поиск, выдать, отменить | PartyView; каталоги поселений и наблюдаемая цель |
| Армия: собрать/распустить | PartyView; сохранён прежний перенос |
| Королевство: создать/вступить/выйти, вассалы, дипломатия | KingdomView/DiplomacyView; прежние matrix/guards |
| Закон: издать/отменить, налог, вотум/прогноз | DiplomacyView; custom policies API, deferred outcome |
| Дети: переименовать, внешность, respec | ChildrenView; stable hero ID, цена config |
| Брак детей: найти чужих детей, предложить, принять/отклонить, отменить | ChildrenView; показанные child/proposal IDs |
| Наследники и журнал наследования | ChildrenView/PropertiesView; heirs и inheritance-log?limit=15 |
| Мастерские: город/тип, купить, продать | PropertiesView; game workshop_types, первоначальный блокер снят разрешённым merge |
| Караваны: город/имя, купить, продать | PropertiesView; общий 60s cache городов |
| Владения и доход | PropertiesView; старый уже удалённый boost не возвращён |
| Вассальный клан: наследник/имя, создать, переименовать | VassalsView; состояние формы сохраняется при poll |
| Выкуп: показать сбор, внести | RansomView; captured viewer и guard смены пленителя |
| Улучшения клана: раскрыть, выбрать/снять, купить пачку | ClanUpgradesView; pending из API, cap проверяет сервер |
| Достижения: раскрыть, прогресс/награда | HeroAchievementsView; current_value/threshold API |

## Общие разделы и оболочка

| Старые кнопки и локальные элементы | Новый компонент / состояние |
|---|---|
| Bot / Integration / Stats | ViewerShell: Сообщество / Игра / Статистика |
| Shop в общей навигации | В старом HTML это заглушка; рабочий shop.js — магазин RimWorld, перенесён в игру |
| Скрыть / восстановить панель | ViewerShell; сервисы и открытое состояние не пересоздаются |
| Поделиться Twitch ID / повтор входа | IdentityBootstrap; запрос только по нажатию |
| Уведомление о возврате / закрыть | ViewerRuntime; batch показан сразу, ack/refresh сохранены |
| Первый шаг / открыть игру | ProfileView → integration |
| Квесты / закрыть, промокод / активировать, TTS / отправить, багрепорт / отправить | ProfileView; TTS подтверждение, серверные цена и лимит |
| Статистика / обновить, достижения / streak | StatisticsView; три no-store GET |
| Кейсы: открыть один, все, preview, остаток | CasesView; это уже полученные награды, покупки кейсов не добавлены |
| Питомец: мой/магазин, rename, equip, unequip, купить | PetsView; server price, подтверждение покупки |
| Яйцо, PNG/emoji слои, фон, аура/анимации | PetStage; пустой body остаётся пустым по старому контракту, неизвестные slots имеют управление |
| Гильдия: список/детали/назад, создать, вступить, вклад, навык, выйти/распустить | GuildsView |
| Голосование: ставка, предложение, отмена, результаты | VotingView; polls/realtime, исход не обещается по принятой заявке |
| Дуэли: открыть RPS, очередь/отмена, камень/ножницы/бумага, ещё раз, закрыть, рейтинг | CommunityGamesView; старые ручные invite create/accept уже удалены из действующей карточки, мёртвый код не превращён в новую функцию |
| TTT: очередь/отмена, клетка, ещё раз/закрыть, рейтинг | CommunityGamesView; room ID, realtime, poll |
| Канат: очередь/отмена, тап, закрыть, рейтинг | CommunityGamesView; batch 1000ms |
| Социальная семья: список/предложить/отклонить/развод/закрыть | SocialFamilyView |
| Социальная семья: принять выбранную заявку | **Заблокировано**: текущий API игнорирует выбранного отправителя, тест реального handler доказывает Bob→Carol |
| Настройки стримера: статус, enable/disable питомцев | ConfigApp; оригинальный public GET/JWT POST |

## RimWorld и ShedColony

| Старые кнопки и локальные элементы | Новый компонент / состояние |
|---|---|
| Viewer/status/колонисты, ручной refresh пешки | RimworldView/Controller |
| Создать/имя, лечить/cooldown, воскресить | RimworldController; config prices, результат заявки и серверный cooldown |
| Удалить trait / gene | Наблюдаемые def/degree/label, цена config |
| Магазин: категории, поиск, обновить, детали, купить предмет | CommerceView; каталог API, подтверждение |
| Имплант: посмотреть части тела, левая/правая, купить | CommerceView; актуальный my-pawn и part_hint |
| Черта/ген: купить | expected_price из показанного каталога |
| Ксенотип: открыть, поиск/выбор/сменить/закрыть | Каталог API; item_def + def_name; текущий ксенотип API не публикует, UI сообщает отсутствие данных |
| Нейротренер: поиск/купить/закрыть | train-skill, серверный каталог |
| Страсть: список навыков, поднять/сбросить, закрыть | pawn-skills цены, подтверждение, observed skill |
| События: поиск/фильтр, купить | Каталог, строковый event_id; выдуманный старый 5min UI lock не скопирован |
| Colony: вкладки Колонист/Экипировка/Колония, аккордеоны | ColonyView; выбор сохраняется через poll |
| Spawn, работа, дом, XP/навык, просьба, еда/болезнь/лечение/траур/счастье | Все действия из исходной inventory; config catalogs и capacity |
| Предмет, смена пола, телепорт, четыре брони, инструменты/оружие/щит | Все действия из исходной inventory; подтверждение цены сервера |
| Guard/patrol, retreat, auto-work | Наблюдаемые job/targets, payload старой панели |
| Festival/visitor/quest/spy, supply, minimum stock/qty | Серверные каталог/цена, capacity/stale guards |
| Clear backlog/building, start/finish research, upgrade building | Показанные координаты/branch/research; отказ остаётся за сервером/игрой |

Каждое из 33 ShedColony action controls независимо извлечено из старого исходника
в тесте матрицы; они не заменены одним успешным примером.

## Что означает parity

Legacy VM исполняет неизменённый старый JS. Сравниваются method/path/query,
сырые JSON-байты, JWT, cache, polls, delayed tails и usage/activity. У section
harness сравнивается весь выбранный host; whole-shell harness дополнительно
запускает настоящий DOMContentLoaded/onAuthorized и проверяет совместный
startup/минуты/5 минут. Не каждый возможный клик каждой формы повторён в
whole-shell режиме: подробные action matrices и интеграционные сценарии
дополняют друг друга. Это ограничение доказательства, не скрытая фильтрация
неудобных запросов.

Платные подтверждения, удалённые выдуманные цены/лимиты/таймеры, отсутствие
ненужных RimWorld GET на Bannerlord и остальные точечные отличия имеют тесты
и причины в коммитах/DEFERRED. Forge expected_item_id — исходное принятое
исключение. Непроверенные production/игра/Twitch и серверные CAS-пробелы
перечислены отдельно в итоговом отчёте.

## Review промежуточного f00c7f0

Три runtime-дефекта подтверждены red и исправлены в 2091d24 (RimWorld JWT busy,
Colony slow polling, строгие pre-action 403/429); детали и доказательства:
docs/PANEL_FULL_PORT_REVIEW_FIXES_2026-10-03.md. Voting unknown outcome оставлен
явным унаследованным ограничением: повторный взнос может списать деньги второй раз.
Обычные Colony игровые fixtures созданы вручную; реальные ASGI captures здесь
доказывают только policy/auth отказы. XSS-аудит был остановлен ограничениями среды,
не владельцем. Артефакты f00c7f0 промежуточные; публикация не разрешена.
## Второй review: Colony и remount оболочки

Checkpoint e5ab10e/Library report v1 промежуточный. При JWT-resolving ViewerShell
размонтировал ColonyView, который терял pending/unknown guard. Red f264ac2:
8 failed/2 passed; fix6a048385b144199b56772eb8d0ac444baf741d49: состояние действия
хранится в ColonyController по shedcolony/channel/login. Затронутые86/86,exit0.
Смена identity/channel/game не переносит guard на другого владельца и не стирает
его при возврате; поздний исход сохраняется для исходного owner. Определённые
429/успех и raw traffic сохранены. Это не серверная идемпотентность и не защита
после полного reload. Подробности: docs/PANEL_COLONY_REMOUNT_REVIEW_2026-10-03.md.
Большой пакет и report v1 до повторного review не заменяются. Публикации нет.

## Финал после независимого re-review

Родитель подтвердил закрытие Colony-remount замечания и отсутствие новых найденных
runtime-дефектов6a048385 относительно e5. Reviewer читал код/evidence, собственные
прогоны не делал. Общий checkpoint23aca6b: suite1251 passed/2 skipped,57 мутаций,
browser188 снимков; два HTTP-теста повторены2/2 на том же runtime. Последующие
коммиты меняют только документацию/evidence. Финальный экспорт целостный, большой
e5 ZIP не используется как новая поставка. Полный reload, транспортные повторы,
идемпотентность, social marriage accept, Voting и DTO-ограничения остаются явными.
XSS-аудит остановлен ограничениями среды/инструментов, не пользователем.
Push/PR/deploy/Twitch submission не выполнялись и не разрешены.
