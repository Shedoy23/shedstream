# Claude: импорт и проверка полного Preact-кандидата

Сначала прочитать PANEL_FULL_PORT_RESULT_2026-10-03.md, COVERAGE и RECONCILIATION.
Функциональный блокер кнопки: принятие социального брака — реальная серверная
ручка игнорирует выбранного отправителя. Её не включать обходным клиентским
решением. Непубликуемые данные/котировки и CAS-ограничения перечислены в отчёте.

Исходная база b2064f4b045025d33d05aaf166ca1694ae0f5475. Ветка
feature/panel-preact-full включает отдельно разрешённый локальный merge
progression1682ebf через e66e8209. Backend/mod/legacy импортированы только этой
интеграцией; после неё самостоятельно не менялись. Точный HEAD пакета — DELIVERY.json.

## Импорт в отдельный checkout

Финальный компактный ZIP содержит все tracked исходники `sources/frontend-next`,
полный `panel-preact-full.patch`, актуальный `build/`, документы, актуальные
evidence и `COMMITS.txt`. Это единый новый checkpoint, старый e5 ZIP не нужен.
Точный HEAD/tree — DELIVERY.json. Применить patch в отдельной ветке от точной
базы b2064f4b045025d33d05aaf166ca1694ae0f5475: `git apply --check`, затем
`git apply --index`. `git write-tree` должен совпасть с DELIVERY.json.
Все файлы frontend-next доступны напрямую; неизменённые backend/моды берутся
из исходного репозитория. История причин/red→green перечислена в COMMITS.txt.

Следующие bundle-команды относятся только к сохранённому промежуточному большому
локальному экспорту, не к финальному компактному пакету. Не применять его как
последний документальный HEAD и не накладывать одновременно bundle и patch.
Ничего не применять поверх незакоммиченной работы и не перезаписывать ветки.

```text
git bundle verify panel-preact-full.bundle
git fetch panel-preact-full.bundle feature/panel-preact-full:refs/heads/review/panel-preact-full-delivery
git worktree add ../panel-preact-full-review review/panel-preact-full-delivery
```

Если review-ветка уже существует, выбрать другое имя без force. Альтернатива:
создать отдельную ветку от точной базы, выполнить `git apply --check` и затем
`git apply --index panel-preact-full.patch`. Patch — конечная разница с базой,
он не сохраняет последовательность коммитов. Bundle и patch вместе не применять.
`source.zip` содержит полный tracked tree ветки; untracked/ignored рабочие
файлы, .git, БД, node_modules и реальные credentials в него не включаются.
`build/` — локальная same-origin сборка для review, не Twitch submission ZIP.

## Воспроизведение

Проверенные локальные инструменты: Node24.19.0, Preact11.0.0, TypeScript7.0.2,
Vite8.3.2, Vitest5.0.3, Playwright1.58.2, Chromium145.0.7632.6. Это локальные
версии, не проверка свежести registry. Устанавливать из lockfiles, не запускать
audit fix попутно. Нужен Python с requirements-contract-tests.txt.

```text
npm ci
npm --prefix frontend-next ci
python -m venv .venv
.venv/Scripts/python -m pip install -r frontend-next/requirements-contract-tests.txt
```

Задать PANEL_BACKEND_PYTHON абсолютным путём к созданному Python. Из frontend-next:

```text
npm test -- --maxWorkers=2
npm run build
node scripts/full-port-browser.mjs
node scripts/measure-build.mjs dist panel-mobile.html src/common/CommonView.tsx src/common/bannerlord-entry.tsx src/panel/TournamentPanel.tsx
node scripts/mutate-full-port.mjs
```

Мутации запускать только после коммита исходников, отдельно от остальных
тестов/build. Runner восстанавливает точные собственные байты в finally;
успех означает red exit1, green exit0, problemNamed true и restored SHA.
Browser script поднимает loopback4187, получает synthetic fixtures, локально
подменяет Helper, блокирует внешние запросы, сохраняет 1280/375. Sandbox включён,
CSP bypass выключен. При необходимости задать PANEL_BROWSER_PATH. На данном
Windows TEMP/TMP были C:\WINDOWS\TEMP. Не отключать ограничения браузера.

Из корня репозитория:

```text
node scripts/run-frontend-tests.mjs
npm run lint:js
node scripts/frontend-globals.mjs --self-test
python scripts/lint_consistency.py
```

Два opt-in HTTP теста намеренно skip без локального сервера. Запустить
`python scripts/run-skillgames-local.py --allow-local-demo --port 4180`, затем
LOCAL_TEST_BASE_URL=http://127.0.0.1:4180 и `npm --prefix frontend-next run test:live`.
Runner создаёт одноразовую SQLite и synthetic credentials, не обращаться к production.

## Что продолжать отдельно

- Backend social accept: выбрать конкретную заявку/отправителя транзакционно.
- Контракт current xenotype/метаболизма и expected-object/price для описанных ручек.
- Свита: точные game-owned upgrade eligibility/quote вместо inherited approximation.
- Настоящая игра, physical phone, Twitch Hosted Test и CDN timing только отдельной
  проверкой. Локальные107592gzip не доказывают<3секунд в Twitch.

Публикация НЕ разрешена: не push, GitHub writes, PR, merge remote, deploy или
Twitch submission. Брать актуальное отдельное разрешение владельца перед выпуском.
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
