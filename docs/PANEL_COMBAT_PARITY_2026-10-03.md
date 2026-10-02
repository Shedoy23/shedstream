# Preact: «Боевые действия», проверка 02–03.10.2026

## Граница результата

Следующая законченная область после развития и снаряжения: **«Боевые действия»**.
Код работает в отдельном новом входе `frontend-next/panel-{extension,mobile}.html`.
Нынешний frontend, backend, моды, OBS и production не изменены. Эта работа не
выполняет merge, публикацию, деплой или установку мода. Публикацией ветки отдельно
занимается интегратор.

**Турниры не перенесены**: это следующий самостоятельный механизм по утверждённому
плану. Вместо неработающей имитации очереди/прогноза показана честная строка о
действующей панели. Не заявляется перенос всей старой вкладки «Бой».

Исходный checkpoint двух областей: `05acd8c`; реализация боевых действий и финальный
60-секундный balance dependency: `5da6e79`; воспроизводимые проверки мутаций:
`c45fe61`. Последующий документный commit не меняет этот код.

## Что перенесено

| Часть | Проверенный контракт |
|---|---|
| Состояние боя | Spectator/живой/routed/unconscious/killed, HP и полоса, участники, убийства, XP, legacy награда и version-2 estimate/paid/failed/unavailable; итоговая разбивка участия/героя/свиты |
| Стойки | Оборона, Баланс, Натиск; повтор текущей стойки тоже запрос; тело только `stance` + client ID |
| Приказы | Все 8 кнопок; порядок hold/charge/skirmish/raid/attach/walls/gate/detach; серверная цена; строгий boolean siege для стен/ворот |
| Призыв | Обе стороны, точный `side`, независимые `player.spawn:player` / `player.spawn:enemy` cooldowns |
| Старые классы | Все 9 действительно выдаваемых активок через 7 текущих классов; точное тело `price` + `power_key`; неизвестный ключ не создаёт кнопку |
| Новая сборка | Все 7 `weapon_type`, включая `thrown`; bow/crossbow остаются разными кнопками при одном power_key; selected/common activation без поля price |
| HUD/доступность | Активные buffs, абсолютные сроки, серверные cooldowns, личный живой участник, pending, выбранное/доступное оружие, реальный баланс |
| Представление | Известные section order/visibility/labels из UI config version 1; тексты экранируются, неправильный config возвращает штатные значения |
| Асинхронный исход | `my-hero.recent_refunds`: одно глобальное уведомление на action_id, 6 секунд, точный старый локализованный текст, безопасный fallback неизвестной причины |
| Общий host | Боевые действия по умолчанию, прежний сохранённый hero/inventory/combat выбор; открытие вкладок, hidden equipment success tail, 8s/2.5s/2s/1s/60s lifecycle, телеметрия |

`can_manage` проверяется при смене сборки. Оно **не** блокирует боевую активацию:
реальные build-combat fixtures имеют `can_manage:false`, а selected/common powers
при живом участнике остаются доступны. Новый режим после обнаружения enabled/version1
не откатывается к старым классовым кнопкам при отсутствии снимка.

Общий синхронный build-family lock охватывает специализацию, стартовый комплект,
выбор оружия и новую активацию. Разные legacy powers и противоположные призывы
сохраняют независимые per-choice locks. Success означает **заявку в очереди**, а не
доказанное применение силы в игре.

## Источник данных и честный старый oracle

`test/panel-fixtures/generate-responses.py` сохраняет первые две области и запускает
отдельный `generate-combat-responses.py`. Последний создаёт **98 ответных записей**,
38 успешных действий через настоящую внешнюю action route, её cash register и
временную SQLite со всеми миграциями. Refund fixtures проходят настоящий
`_on_action_failed`, затем `my-hero`. Есть реальные cooldown, insufficient funds,
not_in_battle, power_not_selected, weapon_unavailable, build_not_ready refusals,
offline/prisoner/syncing/pending build states.

Это **direct handler provenance**, не combat HTTP, не подключённый мод и не игра.
7 weapon definitions разобраны из `HeroBuildPolicy.cs`; representative battle fields
соответствуют `KillRewardBehavior.PushStatsSnapshot`. Fixture со всеми доступными
оружиями покрывает ветки, но не изображает обычный реально надетый комплект.
Идентичность, save/session/hero и эффекты, которые сервер добавляет в очередь,
сохранены отдельно от viewer request. Клиент их не придумывает и не посылает.

Harness оценивает **все 23 локальных старых скрипта без изменений**, в исходном
порядке `extension.html`, в самостоятельном jsdom. Используются реальные DOM-кнопки,
рендереры, dispatcher и collector. Неизвестный маршрут роняет тест, никаких
permissive fallback или фильтрации лишних запросов нет.

Инициализация намеренно ограничена тремя перенесёнными областями. Полный старый
DOMContentLoaded/Twitch bootstrap и неперенесённые hosts не запускаются. Для buffs
регистрируется точное исходное timer statement `_bannerlordBuffTickId` из старого
файла: selector требует ровно одно совпадение и падает при дрейфе. Countdown бизнес-
логика не переписана второй раз в тесте. Read-only таймеры соответствуют выбранным
hosts: 8s hero/classes/build и active inventory, 2.5s buffs, 2s battle, 1s display.
Общий `loadUserData` каждые 60s оставлен и **при hidden document**, как настоящий
`safeInterval`; иначе пассивный доход мог навсегда оставить способность disabled.
Этот таймер не перезапускает фазу при разрешении обновлённого токена того же viewer.

Начальная проверенная последовательность default combat host:
config(no-store), my-hero, classes, build, my-buffs, stats(no-store), level, duels,
battle-status, дополнительный my-buffs на inactive→active. Сохранённые вкладки
проверены отдельно на первоначальную видимость; полный startup-тrace восстановленного
inventory не заявляется идентичным полному старому приложению. Его защищённое чтение
остаётся привязано к observable hero identity, как в предыдущем checkpoint.

Каждая wire-проверка сравнивает **метод, путь, query, JSON body, JWT, Content-Type,
cache**, где применимо keepalive, порядок и кратность read/poll/tail/usage запросов.
Нормализуются только случайные client_action_id/batch_id. Response action IDs не
стираются: они нужны для проверки позднего отказа собственной стойки.

## Явные безопасные отличия от старого frontend

1. **Нет запасных бизнес-цен.** Отсутствующая, отрицательная, строковая или
   нечисловая цена блокирует действие; корректный ноль разрешён. В старом коде
   встречаются fallback 30/10/50/100 и ноль для отсутствующей цены способности.
   Цены и отказы всё равно окончательно проверяет backend.
2. **Cooldown сразу по смысловому ключу.** Старый dispatcher локально записывал
   `power.activate`/`player.spawn`, хотя renderer искал power_key/side-key. Новый
   сразу использует серверную длительность с правильным ключом. Повторный клик
   до следующего poll поэтому намеренно отличается: лишнего POST нет.
3. **Откат отвергнутой стойки.** HTTP refusal возвращает подтверждённую стойку.
   Поздний отказ мода сопоставляется с action_id и revision; отказ старого выбора
   не сбрасывает более новый. Старый клиент сохранял optimistic highlight.
4. **Принадлежность и завершённые снимки.** Stale old-user responses, pre-ack build
   и cooldown snapshots, unmount и unknown-outcome защищены. Обычный успешный
   завершённый poll применяется, даже если более новый ещё в пути. После
   неопределённого результата новые mutations этой identity запрещены до конца
   жизни transport, безопасные чтения доступны; слепой повтор не предлагается.
5. **Fail closed при утрате текущих данных.** Ошибка buffs/battle/build убирает
   зависимую возможность нажать, не открывая legacy fallback. Unknown balance не
   означает бесконечные деньги. Нечисловые суммы/HP безопасно ограничены при показе.
6. **Локальный order cooldown не пропадает при battle rerender.** Старый renderer
   каждые 2s мог временно включить кнопку до следующего общего 1s ticker; новый
   повторно проверяет текущие данные при dispatch. Финальное решение на сервере.

Намеренно сохранён странный старый legacy raid whitelist: `knight` без нового
mounted build не получает «Набег». Это не исправление механики игры под видом
миграции UI. Неизвестные HTTP refusal messages отображаются безопасным текстом;
сырые неизвестные диагностические причины из asynchronous refund не раскрываются.

## Доказательства red → green

- `242e68c`: tests-first, первый запуск 50 failures на отсутствующем combat startup
  и его реальных controls/dependencies; исправление `a0a1d3f`
- `cfef4f2` / `8f44eee`: реальные красные affordance и overlapping stance tests
  (отдельно исправлен подсчёт mutation POST, который сначала включал identity
  resolver POST); исправление `b27c375`
- `8305543`: 3 failures на поздних отказах/уведомлениях; исправление `8cf41e0`
- `627d7db`: 4 failures на 60s balance dependency и старых countdown labels;
  исправление `5da6e79`
- **24 семантические мутации: все exit 1**, затем точное восстановление из
  собственных byte backups и полный зелёный suite. Код до каждого прогона
  закоммичен. Проверяются payload/price/key каждой семьи, shared weapon CD,
  participant, malformed price, family lock, transition read, client ID, tail,
  pending/cooldown revisions, balance cadence/gate, stance identity, viewer
  ownership, actual collector key и section order
- Viewer ownership имеет два независимых барьера: abort и generation. Первое
  снятие только generation сохранило зелёный тест благодаря abort. Корректная
  adversarial mutation снимает оба, получает exit 1; это не скрытый выживший mutant

[Воспроизводимые команды и результаты мутаций](evidence/panel-combat-2026-10-03/mutations.json).
Runner: `python frontend-next/scripts/check-combat-mutations.py <output-dir>`.

## Финальные проверки

| Проверка | Результат |
|---|---|
| Исходные 321 + 142 новые unit/DOM tests | **463 passed**, 2 explicit live skips, exit 0 |
| Typecheck | exit 0 |
| Build и check-build | exit 0: 6 entrypoints, CSP/Helper first, парные HTML, независимые графы, readable sources и лицензии |
| Fresh self-contained build | отдельный `git archive`, собственный `npm ci --offline`, exit 0 |
| Реальные HTTP мини-игры | **2 passed**, exit 0 на новом disposable local server; морской бой и 6 побед сапёра, без browser/visual claims |
| Combined fixture generator | exit 0; свои временные БД/конфиги, исходные golden files возвращены из своих точных backups |
| Защищённые области | diff относительно `05acd8c` для legacy/backend/mod/OBS/frozen dist пуст |

Команды: `npm --prefix frontend-next test`, `npm --prefix frontend-next run build`,
`LOCAL_TEST_BASE_URL=http://127.0.0.1:<port> npm --prefix frontend-next run test:live`.
Generator требует заявленные backend test dependencies; локально использован
`/tmp/preact-backend-venv/bin/python`. Первые два fixture/test набора не заменены.

## Вес

Чистая отдельная сборка: `panel-mobile.html` и весь его initial import graph:
**148 804 bytes raw / 41 864 bytes gzip-9**. Предыдущие две области:
114 632 / 32 980 bytes. Добавление полного боевого экрана и общей зависимости
уведомлений/баланса: **+34 172 raw / +8 884 gzip-9**.

Метод: `node frontend-next/scripts/measure-build.mjs frontend-next/dist panel-mobile.html`,
`gzip -9 -c` отдельно для каждого файла. [Все файлы и суммы](evidence/panel-combat-2026-10-03/sizes.json).
Не входят внешний Twitch Helper, API ответы и sourcemaps в initial traffic.
`minify:false`, `cssMinify:false`, `sourcemap:true` сохранены. Не делается вывод о
размере всей старой панели, фактическом CDN-сжатии или времени сети Twitch.

## Что не проверено

Браузерный loopback остаётся запрещён, компьютер владельца был offline. Обхода
ограничения нет. **Живой браузер, визуальная раскладка, 318 px/телефон, Twitch Hosted
Test, реальный Bannerlord и фактическое действие приказа/способности в игре не
проверены.** CSS содержит узкий breakpoint, но это не доказательство визуального
качества. Перед использованием нужна проверка глазами и дальнейший review.
