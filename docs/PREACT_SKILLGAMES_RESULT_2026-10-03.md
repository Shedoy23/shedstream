# Preact: результат ночной миграции мини-игр, 03.10.2026

**Статус: проверенный код-кандидат; обязательная живая браузерная проверка остаётся открытой.**

Ветка `feature/skillgames-preact` начата от свежей опубликованной `feature/skill-minigames`
`8a40391b397ba15526179e6de10830fdb912b16c`, а не от прежней локальной поставки.
Миграция и исправления runtime: `2dbbd8f`; полный проверенный код/тесты: `b3c307d`.
Production, Twitch submission/release, merge, старый фронт, ZIP, backend, моды и OBS не менялись.

## Вес: одинаковый метод до/после

Node 24.19.0 / npm 11.9.0. Сначала чистые `npm ci` и `npm run build` на React-базе,
затем те же команды с Preact. Метод: `gzip -9 -c <file>`, каждый файл отдельно;
размеры в байтах (не KiB). Все файлы `dist/assets/*`, включая карты исходников:

| До: файл | Raw | gzip-9 |
|---|---:|---:|
| `assets/jsx-runtime-DC628G0m.js` | 566,629 | 107,130 |
| `assets/jsx-runtime-DC628G0m.js.map` | 985,151 | 189,519 |
| `assets/main-BcDcf8_c.css` | 7,137 | 2,236 |
| `assets/main-EyaNeoM3.js` | 63,190 | 15,788 |
| `assets/main-EyaNeoM3.js.map` | 100,755 | 26,921 |
| `assets/tournament-DXEIGRqF.css` | 4,335 | 1,540 |
| `assets/tournament-gpfgBUNN.js` | 20,163 | 5,264 |
| `assets/tournament-gpfgBUNN.js.map` | 29,173 | 8,690 |

| После: файл | Raw | gzip-9 |
|---|---:|---:|
| `assets/jsxRuntime-BR6Z_TYL.js` | 24,926 | 8,856 |
| `assets/jsxRuntime-BR6Z_TYL.js.map` | 172,675 | 51,778 |
| `assets/main-6XLBR_24.js` | 58,169 | 15,430 |
| `assets/main-6XLBR_24.js.map` | 97,126 | 26,786 |
| `assets/main-BcDcf8_c.css` | 7,137 | 2,236 |
| `assets/tournament-D8eK_sZD.js` | 18,097 | 5,176 |
| `assets/tournament-D8eK_sZD.js.map` | 27,996 | 8,702 |
| `assets/tournament-DXEIGRqF.css` | 4,335 | 1,540 |

| Объём | До raw | После raw | До gzip-9 | После gzip-9 |
|---|---:|---:|---:|---:|
| Все assets, с sourcemaps | 1,776,533 | 410,461 | 357,088 | 120,504 |
| JS+CSS всех входов, без sourcemaps | 661,454 | 112,664 | 131,958 | 33,238 |
| Первая загрузка mobile: HTML + полный импортный граф | 637,818 | 91,093 | 125,625 | 26,996 |

**Первая загрузка приложения: 91 093 raw / 26 996 gzip-9 байт**, против 637 818 / 125 625.
Снижение примерно 85,7% raw и 78,5% gzip. Общий runtime Preact 24 926 raw вместо
566 629 raw React: примерно в 22,7 раза меньше, а не обещание «весь фронт в 30 раз».

Для mobile считаются `mobile.html`, общий runtime, `main` и его CSS. Турнирный вход и
sourcemaps не являются первым сетевым графом mobile. Старые `viewer*.js` сюда не входят:
новый вход не загружает старую панель. Внешний неизменный Twitch Helper и ответы API
в эти числа не включены; результат **не является полным сетевым замером Twitch**.

Цель приложения ≤200 КБ gzip выполнена. CDN Content-Encoding и реальное время первого
показа не измерены: gzip — локально рассчитанный размер, не утверждение о настройке CDN.
Правила Twitch относятся к первой мобильной загрузке, а не к размеру репозитория/ZIP:
≤1 МБ и <3 с при ~500 Кбит/с. Даже 200 КБ сами по себе дают ~3,2 с передачи без прочих
затрат. Hosted Test/телефон остаются обязательными, соответствие Twitch не заявляется.
Источник: https://dev.twitch.tv/docs/extensions/guidelines-and-policies/ (§3.2–3.3).

Машинные результаты: [до](evidence/preact-2026-10-03/before.json),
[после](evidence/preact-2026-10-03/after.json). Воспроизведение:

```sh
npm --prefix frontend-next ci
npm --prefix frontend-next run build
node frontend-next/scripts/measure-build.mjs
```

## Что изменено и что поймали тесты

1. `preact@11.0.0` закреплён точно: на момент установки это stable/latest npm. React,
   ReactDOM, scheduler и React type/runtime packages удалены. JSX использует Preact;
   точные aliases для compat/client/JSX/test-utils согласованы между TS, Vite и Vitest.
2. React 19-only API (`use`, useActionState/useOptimistic/useFormStatus, server components,
   function form action, ref как пользовательский prop) в src не найдены. Переделка
   механики не понадобилась. Testing Library заменена на native Preact-версию, чтобы
   peer dependencies не возвращали настоящий React.
3. **Первый быстрый клик мог потеряться.** Отложенный Preact passive effect перезаписывал
   черновик флота и закрывал только что открытое подтверждение выхода/сброса/прогноза.
   Инициализирующая синхронизация перенесена в layout effect. Тесты специально удерживают
   passive frame и нажимают настоящий DOM `.click()` без `act`, который скрывал гонку.
4. **autoFocus не переносил фокус, как в React.** Подтверждение прогноза теперь получает
   фокус явно и возвращает его кнопке запуска при закрытии; аналогично быстрым игровым
   подтверждениям. Проверены Cancel/первое открытие и отсутствие случайной отправки.
5. **Обычный Vite sourcemap терял читаемые исходники Preact.** Вместо оригиналов оставались
   upstream dist-файлы по 2 строки. Узкий build loader компонует опубликованные карты
   Preact; runtime JS не подменяется. В сборке теперь 27 оригинальных исходников core,
   hooks, compat и JSX. Независимое сравнение с/без loader подтвердило одинаковый JS
   после нормализации имён файлов и ссылки sourceMappingURL.
6. `minify:false`, `cssMinify:false`, `sourcemap:true` сохранены. Проверка сборки не только
   считает строки: проверяет оригинальные sourcesContent, отсутствие React/scheduler,
   Twitch Helper первым, CSP, изоляцию турнира и MIT notice Preact с точной версией.
7. Два live HTTP файла используют одну временную пару игроков: `test:live` и любой полный
   запуск с `LOCAL_TEST_BASE_URL` сериализованы, чтобы тесты не дрались за чужую партию.

## Доказательства red → green

| Проверка | Красный результат | После восстановления/фикса |
|---|---|---|
| Черновик флота после быстрого первого клика/обновления токена | host regression exit 1 | exit 0 |
| Фокус подтверждения прогноза | отдельный test commit `c105505`, exit 1 | exit 0 |
| Быстрые quit/restart подтверждения | test commit `f159417`, 2 падения, exit 1 | exit 0 |
| Быстрый прогноз, возврат passive reset | regression exit 1 | exit 0 |
| Выстрел B2: временно cell 8 вместо 7 | behavioral test exit 1 | exit 0, файл совпал с собственной копией |
| Удаление waiting text / снятие generating gate | две мутации, каждая exit 1 | оба DOM-теста exit 0 |
| Отключён loader оригинальных Preact maps | check-build exit 1 | exit 0 после rebuild |

Мутации делались после коммита, восстанавливались из собственных копий; финальная
сборка выполнена после всех восстановлений. Никакая намеренная поломка не оставлена.

## Проверки

| Этап | Результат |
|---|---|
| React baseline | 107 passed, 1 live opt-in skip; typecheck/build/check-build exit 0 |
| Чистый Preact npm ci, полный unit/DOM | 114 passed, 2 explicit live skips, exit 0 |
| Typecheck/build/check-build | exit 0 |
| Два real HTTP файла вместе, pinned backend | 2/2, exit 0 |
| Старые frontend gates | 17/17; JS lint/globals selftest exit 0 |
| Consistency с pyflakes | exit 0, 0 lint warnings |
| Все backend standalone tests локально | 144/145: единственный блок — отсутствует PowerShell для frontend freeze gate |
| Независимый review | найденные lifecycle/focus/source-map проблемы исправлены; открытых code blockers не найдено |

Backend-тесты запускались с отдельными pinned requirements-test (FastAPI 0.104.1,
Pydantic 2.13.5, aiosqlite 0.19.0), и `RIMWORLD_PRICES_PATH` во временной папке:
default config пытается создать каталог в недоступном home. PowerShell gate честно
возвращает exit 1 при отсутствии интерпретатора. Прежний переносимый `/tmp` runtime
в этой среде не сохранился; этот локальный aggregate **не называется полностью зелёным**.
Полный CI после публикации проверяется отдельно на точном SHA; его статус не подменён
зелёной проверкой исходной ветки. Vite предупреждает о будущей смене native config loader;
это warning, текущие команды завершились exit 0.

## Реальные локальные игры и жалоба «сапёр не стартует»

Штатный `scripts/run-skillgames-local.py --allow-local-demo --port 4180`: настоящие
production routes/service/engine, временная SQLite, синтетические Twitch-личности.
Через production frontend transport/controller сыграно 3 beginner + 3 advanced до победы.
Решатель видит только открытые числа, флаги и публичные размеры/число мин; seed/мины/
сертификат и внутренние данные БД не читаются. Advanced потребовал subset-дедукции.
Морской бой прошёл queue → ручная/авто расстановка → ready обеих сторон → 66 реальных
выстрелов → completed (Alice win, Bobby loss). Свежий identity/transport восстановил
доску и окончательный результат. Выходом/forfeit тестовые игры не завершались.

Последний совместный прогон: POST start 5,7–10,6 мс; POST первого открытия 9,8–16,1 мс.
С учётом controller reconciliation: запуск 11,1–17,8 мс; первое открытие 21,5–30,3 мс.
Это localhost этой машины, а не телефон, CDN, production-нагрузка или SLA генератора.
В отдельном pinned прогоне состояние generating реально наблюдалось в 3 партиях.
DOM/controller тест отдельно держит ответ первого открытия 8 виртуальных секунд:
видно «Ждём ответ сервера…», повторные действия закрыты, после ответа поле доступно.
Восстановленный generating показывает пояснение сервера и заблокированные клетки.
На этом стенде жалоба о нестарте не воспроизвелась; причину на устройстве владельца
не удалось установить, и такой вывод не выдаётся за исправление этой конкретной жалобы.

```sh
python -m pip install -r Расширение/backend/requirements-test.txt
npm --prefix frontend-next run build
python scripts/run-skillgames-local.py --allow-local-demo --port 4180
# В другой консоли на той же машине:
LOCAL_TEST_BASE_URL=http://127.0.0.1:4180 npm --prefix frontend-next run test:live
```

В облачном sandbox отдельные exec изолируют loopback; сервер и тесты запускались одним
shell с background process и trap cleanup. Для обычной локальной машины это не требуется.

## Не проверено: явные незакрытые пункты плана

- **Живая игра через браузер в двух вкладках и визуальные 318 px НЕ выполнены.** Cloud CUA
  отверг `http://127.0.0.1:4180/extension.html?player=alice` как `ERR_BLOCKED_BY_CLIENT`.
  Блок не обходился публикацией, прокси, другим browser driver или отключением защиты.
  HTTP/DOM сценарии выше не заменяют этот критерий «готово».
- Нет реального телефона, Twitch Hosted Test, реальных Twitch token/identity flows,
  CDN gzip/timing, slow-network timing или production-генерации под нагрузкой.
- Нужны две вкладки alice/bobby на штатном локальном стенде, визуальная партия морского
  боя и обе победы сапёра, в том числе 318 px и длительное ожидание генератора. Затем
  разрешённый отдельно Hosted Test. До этого ветка остаётся кандидатом.
- Никакой автоматической выкладки/слияния/новой подачи в Twitch нет.
