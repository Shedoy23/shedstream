# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**shedstream / ShedLink** — a multi-tenant Twitch Extension platform that turns viewers into participants in the streamer's game. One backend deployment serves many streamer channels. Three game modules are declared today: **Bannerlord** (C# mod + backend module — the flagship), **RimWorld** (RimLink — part legacy monolith `rimworld.py`, part Module API adapter; which game is live is a fact about the channel, not about the code — check `channels.active_module` and the mod heartbeat, never assume. The old line here said RimWorld was "effectively off"; that belief got baked into the paid-action TTL sweeper and left 550 crustics stuck on the 2026-09-10 RimWorld stream → `docs/POSTSTREAM_TRIAGE_2026-09-10.md`), and **shedcolony** (MineColonies × Twitch, early; game-side mod lives in a separate repo). The architecture goal is game-agnostic: games plug in via the Module API (`docs/MODULE_API.md`).

## Repo layout (only the parts that need explaining)

- `Расширение/backend/` — FastAPI + SQLite (aiosqlite) backend. Multi-tenant: every tenant table is scoped by `channel_id`.
- `Расширение/backend/modules/<game>/` — per-game adapter (`_adapter.py`) + `manifest.yaml` declaring that game's events/actions/catalogs.
- `Расширение/backend/migrations/` — `m<N>_*.py` migrations, each `async def apply(conn)`.
- `Расширение/frontend/` — the Twitch extension UI: много обычных `<script>`-файлов в ОДНОМ глобальном пространстве имён (см. линтер коллизий и `no-undef`). `viewer.js` — общая оболочка для RimWorld и Bannerlord, игровой код в `viewer-bannerlord.js` (самый большой файл фронта) и `viewer-rimworld.js`. `extension.html` и `mobile.html` — параллельные оболочки, обязаны совпадать. **Числа строк здесь намеренно не пишем:** они протухают молча — строка «viewer.js ~7k» прожила тут полтора месяца после распила файла, и её дважды пересказали владельцу как факт (→ `LESSONS.md`, «Факт в документе имеет срок годности»).
- `BannerlordLink/` — C# Bannerlord mod (Harmony patches, `MissionBehavior`, `CampaignBehaviorBase`). Clean-room re-impl using BLT as reference.
- `RimLink/` — RimWorld module (C# mod + assets).
- `reference/BLT_RC22` + `reference/BLT_lait` — BLT reference checkouts (~17 МБ каждый, вне git). **Read-only, clean-room** (LGPL): ideas/APIs/short idioms only, never copy class bodies. Здесь до 2026-07-26 значилось `БЛТ/` — такой папки в worktree нет, то есть правило клин-рума указывало на несуществующий путь.
- `scripts/` — deploy / consistency-lint / crash-triage automation (see Commands).

## Where the real docs live — read before non-trivial work

Repo root: **`STATUS.md` — витрина «что сейчас»: 10 строк, что на проде / что ждёт деплоя / что горит / ближайшая дата. Открывать ПЕРВОЙ в начале сессии, обновлять в КОНЦЕ каждой.** Дальше: **`RUNBOOK.md` — операционная правда: где что лежит на проде, чем проверять, ловушки, «выглядит сломанным, но это не так». Читать при любой работе с продом, базой, бэкапами, деплоем, публикацией модов — он избавляет от повторного расследования.** `OVERVIEW.md` (what the project is — structure, data flow), `ROADMAP.md` (the owner's stabilization plan — current priorities; check it when the owner asks "what should we do next"), `DEFERRED.md` (что отложено сознательно + «решено НЕ делать»), **`LESSONS.md` — истории инцидентов, из которых выросли правила ниже; открывать, когда правило кажется неверным.** **`RUNBOOK.md` §13 «Вопросы владельца и регулярная уборка» — вопросы, которыми владелец сокращает лишнюю работу; часть из них я обязан задавать себе сам.**

`Расширение/docs/` is the knowledge base. The **`CONTEXT*.md` files are the living per-area status/handoff docs — read the relevant one first**:
- `CONTEXT.md` (core/platform), `CONTEXT_BANNERLORD.md`, `CONTEXT_RIMWORLD.md`.
- Architecture: `ARCHITECTURE.md`, `MULTITENANT_PLAN.md`, `MODULE_API.md`, `ARCH_DATA_OWNERSHIP.md`.
- Twitch frontend releases after public `0.0.1`: `Расширение/docs/TWITCH_UPDATE_RELEASE_PLAYBOOK.md`
  (единственная копия — идентичный дубликат в корне удалён 29.07, чтобы две
  правды не разъехались)
  (new version → Local/Hosted Test → Review → owner-approved Release; EBS must
  support old and new CDN clients during the transition).
- Bannerlord mod: `BANNERLORD_DEV_ENV.md` (build env), `TESTING_PLAYBOOK.md` (in-game verification), `BANNERLORD_API_CHEATSHEET.md` (Bannerlord/TaleWorlds API by task — fast orientation), `BLT_RC22_REFERENCE.md` (deep BLT file-by-file).

## Commands

**Backend** (`cd Расширение/backend`):
- Run: `python main.py` — uvicorn on :8000; runs all migrations on startup (prints `✅ Migrations complete`).
- Compile-check: `python -m compileall -q .`
- Tests are **standalone scripts, not pytest**: `python tests/test_multi_tenant_isolation.py` (also `test_pubsub.py`, `test_eventsub.py`). A failure means a real regression in a tenant/security invariant.
- Deps: `pip install -r requirements.txt`.

**Frontend**: no build step (static JS/HTML served by backend). Syntax-check: `node --check frontend/viewer.js`.

**Bannerlord mod** (C#, net472):
- Build: `dotnet build BannerlordLink/src/BannerlordLink.csproj -c Release` — references game DLLs at `X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord`. Output lands in `BannerlordLink/bin/Win64_Shipping_Client/` (NOT the game folder).
- The DLL must then be copied into the game's `Modules/Shedoy23.BannerlordLink/bin/Win64_Shipping_Client/` (`scripts/deploy.ps1 -Mod` does build + copy + md5-verify). Restart Bannerlord to load it — no hot-reload.
- Edit in this worktree (git source of truth); the `src` copy under the game's Modules folder is stale.

**Automation** (`scripts/`, see `scripts/README.md`):
- `pwsh scripts/deploy.ps1` — one-command deploy (`-All` adds the mod, `-Backend`/`-Frontend`, `-DryRun`).
- `python scripts/lint_consistency.py` — version-sync / migrations-wired / manifest-drift checks (run by CI + the pre-commit hook).
- `pwsh scripts/triage-crash.ps1` — summarize the latest Bannerlord crash dump via dotnet-dump.

## Deploy

Prod = `root@31.130.132.224:/root/twitch-extension/`, run under supervisor as `twitchbot`. Use `scripts/deploy.ps1` (tars `backend`+`frontend` excluding `*.db`/`.env`, scp + extract + `supervisorctl restart twitchbot` + health-check). **Confirm before deploying / restarting prod.** **Backups are DONE — do not report offsite as a gap** (this line said so until 2026-07-25 and got repeated at the owner for weeks). Three tiers: `backend/backup_db.sh` cron + in-process `backend/backup_loop.py` on prod, and offsite on the owner's PC — Windows task `shedstream-db-backup-pull` runs `%USERPROFILE%\shedstream-backups\pull-backup.ps1` daily 13:00, keeps 14 dailies. Each pull now self-verifies via `scripts/verify-backup.py` (unzip → `integrity_check` → key tables non-empty; exit 0 ok / 1 corrupt / 2 could-not-check). A full restore drill was run 2026-06-13 (`docs/RESTORE_PLAYBOOK.md`). Known limit: the PC must be awake — missed days leave calendar gaps, by design not failure.

## Conventions & gotchas that actually bite

Каждое правило — действие, условие и одна строка причины. Полные истории, из
которых они выросли, лежат в `LESSONS.md`; приходить туда, когда правило кажется
неверным и хочется проверить, откуда оно.

- **Multi-tenant scoping is mandatory.** Любой запрос/вставка в арендаторскую
  таблицу несёт `channel_id` — через `resolve_channel_id_or_default()` или JWT
  ContextVar (`require_jwt_user` / `require_jwt_channel`). Пропуск = утечка между
  каналами либо падение по `NOT NULL`. **Держит линтер** `check_tenant_scoping`;
  точечная лазейка — `# tenant-ok: <причина>`; исторический skip с
  `rimworld.py` снят после возврата модуля в активную разработку.
  → `LESSONS.md`, «Multi-tenant scoping».
- **Арендатор — не только строка в таблице; изолируй и ВЫХОД наружу.** У любой
  новой функции спросить: что она отправляет наружу (чат, Telegram, оверлей) и
  откуда берёт адресата и текст. Адресат из умолчания + текст из общего конфига
  = дефект, невидимый пока канал один. Причина: 22.08 нашлось три таких за день,
  и правило выше их не касалось — в БД они ничего не писали. Дешёвый первый шаг
  — сделать умолчание шумным (`channel-default:` в логе) и завести в тесте ВТОРОЙ
  канал. Гейты: `test_multi_tenant_isolation.py` (строки),
  `test_auto_messages_per_channel.py` (побочные эффекты).
  → `LESSONS.md`, «Изоляция ВЫХОДА наружу».
- **Migrations must be wired.** Добавил `m<N>_*.py` — зарегистрируй в
  `main.py:run_migrations()`; линтер валит коммит, если нет. Применённую миграцию
  не редактировать, писать новую. Сид действует только на свежих базах: менять
  прод-строки — отдельным `UPDATE`. Миграция сама пишет себя в
  `migrations_applied` и делает `commit` — иначе её INSERT'ы не сохранятся.
  → `LESSONS.md`, «Migrations must be wired».
- **Новое событие мод→бэкенд обязано быть объявлено в `manifest.yaml`.** Иначе
  бэкенд молча его отбрасывает (`event_not_in_manifest`): мод пишет в лог, БД не
  меняется. Объявить мало — ещё разрулить в `_adapter.handle_event`. Линтер
  `check_manifest_events` ловит литеральные пуши; собранные из переменной — на
  тебе. То же для новых действий. → `LESSONS.md`, «New mod→backend event».
- **Две валюты, не смешивать.** 💎 крустики = очки платформы, 💰 динары =
  `Hero.Gold` в игре, 1💎 = 5💰. Действие берёт ОДНУ валюту по смыслу. Крустики
  **начисляются только в ядре**; в `modules/<игра>/` и `routes/<игра>_*.py` они
  только списываются (рефанд не нарушение). Причина: рента с феодов вырезана за
  то, что зритель богател без участия. → `LESSONS.md`, «Two currencies».
- **Проверка и действие, которое она разрешает, — в ОДНОЙ транзакции.**
  `add_points`/`remove_points` открывают своё соединение и коммитят отдельно:
  краш в этом окне = деньги без эффекта либо двойная награда. Использовать
  `add_points_tx` / `remove_points_tx` на соединении вызывающего, в том же
  `BEGIN IMMEDIATE`. Проверку кулдауна/дедупа перечитывать ВНУТРИ транзакции.
  **Правило НЕ про деньги, а про любое условие, которое что-то разрешает.**
  Формулировка «списание и эффект» читалась как денежная, и 10.09 из-за этого
  ровно тот же дефект уехал на прод в защите ПОРЯДКА снимков: свежесть
  проверялась в одной транзакции, снимок применялся в другой, второй конверт
  успевал пролезть между ними — и зеркало зрителя замирало навсегда, хотя ни
  одной монеты рядом не было. **Признак — граница транзакции, а не `await`.**
  Спрашивать надо «держится ли на записи та же блокировка, под которой читали
  условие», и ответ «нет» дают ещё три случая помимо второго соединения:
  `commit`/`rollback` между проверкой и записью на ОДНОМ соединении, выход из
  `async with`, и вмешательство чужого процесса (`backup_loop`, cron, второй
  воркер) — тому наш `await` вообще не нужен. Плюс `BEGIN IMMEDIATE`, а не
  голый `BEGIN`: отложенная транзакция берёт блокировку записи только на
  первом UPDATE, то есть ПОСЛЕ проверяющего SELECT, и окно остаётся открытым.
  Признак «есть await, открывающий другое соединение» слишком узок — он
  пропускает все четыре (поправлено внешним обзором 10.09). **Условный UPDATE
  не спасает, если следующее действие опирается на чтение ДО него:** 11.09
  опрос мода метил `dispatched` условно, но отдавал игре всё прочитанное без
  блокировки — и отдал заявку, за которую сторож уже вернул деньги.
  Действовать только по тому, что реально захвачено: повторное чтение под той
  же блокировкой или `rowcount`. Класс найден 11× — 11.09 сразу три случая в
  одной жизни заявки: сторож возврата, опрос, сторож `dispatched`
  (`tests/test_module_action_races.py`).
  → `LESSONS.md`, «Charge + effect in ONE transaction».
- **Платное действие обязано детектить тихий no-op ДО ack-true.** Движковый API
  часто молча ничего не делает (кап, дубль, нет цели, оффлайн) — успех без
  эффекта и без возврата. Детект по НАБЛЮДАЕМОМУ эффекту (before/after, «объект
  появился»), не по копии внутренней формулы движка. Признак: результат посчитан,
  но не проверен — если функция вернула «сколько сделано», это условие, а не
  украшение лога. Класс всплывал 5×. → `LESSONS.md`, «Платное действие обязано детектить тихий no-op».
- **Одна запись — одно место.** Прежде чем добавить запись в таблицу, спроси:
  кто ЕЩЁ туда пишет. Два пути одной записи выглядят рабочими, пока копии
  одинаковы, и расходятся молча при первой правке одной из них. Так уже дважды:
  покупка предмета в двух местах и время просмотра из серверного цикла плюс
  heartbeat панели — у зрителя опыт шёл вдвое, и заметили это не чтением кода,
  а числом: 19 096 минут просмотра при 16 352 минутах всех эфиров. Нужна запись
  внутри чужой транзакции — делай `_tx`-версию того же SQL, а не второй
  экземпляр (`record_income_tx`, `add_points_tx`, `add_notice_tx`). Держит
  `tests/test_single_write_path.py`. → `LESSONS.md`, «Одна запись — одно место».
- **Один признак — один смысл.** Перед использованием поля в условии назвать,
  что оно ЛИТЕРАЛЬНО записывает и что нужно проверить; разошлось — нужен
  ВТОРОЙ признак от того, кто знает, а не вывод из размера или свежести.
  Пустой список не отличается от «не знаю», свежий heartbeat — от внимания
  зрителя. Найдя такую склейку, сразу проверить соседние функции: 23.08
  починили ставку за просмотр, а розыгрыш кейсов рядом остался сломан до
  28.08. Класс всплывал 3×, дважды про деньги.
  → `LESSONS.md`, «Один признак — два смысла».
- **Отгружаемый бинарник сверять с исходником, а не с именем файла.** Релиз
  берёт jar/DLL из папки, куда его кладут руками; номер версии у старого и
  нового одинаковый, поэтому подмена не видна. 28.08 так уехали 12 платных
  кнопок на 299 300 крустиков. Гейт: `scripts/check-shedcolony-jar.py` внутри
  упаковщика. → `RUNBOOK.md` §7 «Ловушки».
- **Пользователь ОДИН — метрики не сигнал о продукте.** Ноль значит «он сейчас в
  это не играет», «сломано» или «не нужно», и числом их не различить; третье при
  одном канале не измеряется в принципе. Увидел ноль — проверь кодом и логами,
  работал ли путь; потом спроси владельца. Выводов «не пользуются, можно убрать»
  не делать, пока каналов меньше пяти. Всплеск — это стрим, а не рост.
  → `LESSONS.md`, «Пользователь ОДИН».
- **Убрал механику — прогони тесты и линтеры.** Уборка не закончена, пока не
  зелёные: 29.07 снятие `player.respawn` с продажи молча положило
  характеризационный тест кассы на весь день.
  → `LESSONS.md`, «Убрал механику».
- **Проверять ДЕЙСТВИЕ поимённо, а не «механику».** Два похожих имени в одной
  области = два разных пути; сделанным отмечать только то, что открыл и увидел.
  → `LESSONS.md`, «Проверять ДЕЙСТВИЕ поимённо».
- **Cache-bust обеих оболочек.** `viewer.js?v=...` идентичен в `extension.html` и
  `mobile.html` (`deploy.ps1` синхронизирует). Рассинхрон = часть аудитории на
  старом JS.
- **Патч против краша мода: сначала prefix, потом finalizer.** Ванильный
  daily-tick падает на клановых edge-case героях. Чинить патчем, который
  ПОЧИНИТ вход и пустит ванильный код работать; глотать конкретное исключение —
  крайняя мера, дважды скрывшая мёртвую фичу. Kill-switch:
  `SKIP_PATCH_NAMES` в `BannerlordLinkModule.cs`.
  → `LESSONS.md`, «Mod crash protection».
- **Vanilla NRE: декомпилируй до причины, не глуши вслепую.** Найти конкретный
  null (`ilspycmd`, путь в `LESSONS.md`), написать prefix, который его чинит;
  finalizer оставить бэкстопом с полным стеком. Фикс мода без прогона в игре —
  правдоподобен, но не доказан. → `LESSONS.md`, «Vanilla NRE».
- **Правишь обработчик действия в моде — сначала `docs/MOD_CONTRACT.md`.**
  Обработчик обязан НАЗВАТЬ исход на каждом выходе (`PostApplied` / `PostFailed`),
  успех — только после наблюдения эффекта, `catch` заканчивается отказом. Причина:
  в `MainThreadDispatcher` успех это значение по умолчанию, поэтому забытый путь
  даёт ложный успех и невозврат денег. Пока идёт перевод, действие без исхода
  пишет в лог `БЕЗ ЯВНОГО ИСХОДА` — это и есть список работ.
- **Действия зрителя гейтить состоянием игры с ОБЕИХ сторон.** Требующие клана,
  королевства, лидерства — заблокированы во фронте с причиной И отклоняются на
  бэкенде: фронт обходится.
- **CodeGraph MCP** индексирует репозиторий — «что вызывает X / где X / что
  сломается» спрашивать у него, а не грепом (детали в личном `CLAUDE.md`).
- **Страницы стримера — HTML в `backend/templates/`, не строки в Python.**
  Рисовать через `_render_template()` (jinja2, autoescape ВЫКЛЮЧЕН намеренно —
  экранирует вызывающий код). Шаблон кэшируется, правка требует рестарта.
  Проверка: `tests/test_dashboard_render.py`. → `LESSONS.md`, «Страницы стримера».
- **Тонкий фронт: с бэка данные, во фронте только показ.** Цены, лимиты,
  кулдауны, тексты отказов, каталоги, доступность действий приходят с сервера.
  Причина: фронт замерзает на CDN Twitch до следующего ревью, бэкенд деплоится за
  минуты. Критерий: фронт обязан корректно отрисовать причину отказа, которой не
  знает. Граница: разметку и логику с сервера НЕ присылаем — ревьюер Twitch
  должен видеть, что делает расширение. → `LESSONS.md`, «Тонкий фронт».
- **Платное + асинхронное действие → свой подтверждающий тост.** Если исход
  отложенный (вотум, ставка), на успехе нужен тост «это заявка, исход позже».
  Иначе зритель жмёт снова и переплачивает — так объявляли войну 4 раза подряд.
  → `LESSONS.md`, «Платное + асинхронное».
- **Возврат денег обязан объяснить себя зрителю — в ОБЩЕЙ функции возврата.**
  Любой рефанд пишет `add_notice_tx` в той же транзакции, что `add_points_tx`,
  и именно в функции, которая возвращает, а не в каждом вызывающем: вызывающие
  забывают. Причина: зритель, у которого деньги ушли и молча вернулись, не
  отличает «я сделал не то» от «у них сломалось» и жмёт снова. Класс всплыл
  дважды подряд: 09.09 молчал отказ RimWorld в адаптере, 11.09 — вся старая
  очередь RimWorld, хотя накануне в отчёте она была записана рядом. Держат
  `test_rimworld_refusal_notice.py` и `test_rimworld_abandoned_commands.py`.
  → `docs/POSTSTREAM_TRIAGE_2026-09-10.md`, §4.

## Session workflow rules

Правила процесса. Причина каждого — в `LESSONS.md`; здесь только что делать.
**Соблюдать проактивно, не дожидаясь просьбы.**

1. **Сначала спроси документацию, потом код.** Перед новой механикой,
   починкой в незнакомой области и любым «почему X сломан» —
   `python scripts/docs-search.py <тема>`; найденное прочитать, в сводке
   назвать что нашлось (или что не нашлось — тогда описать тему по ходу).
   Причина: самый частый дорогой промах — заново расследовать записанное;
   офсайт-бэкап числился дырой месяц ПОСЛЕ того, как был сделан. Предложил
   друг владельца 24.08. → `LESSONS.md`, «Факт в документе имеет срок годности».
2. **Check before code.** Перед НОВОЙ зрительской механикой: проверка правил
   Twitch (`/twitch-compliance`), отметка про лицензию если идея зеркалит BLT,
   спека на 5–10 строк и явное одобрение. Просят «просто сделай» — проверки всё
   равно сначала. Причина: каждая дорогая ошибка проекта — «построили, потом
   узнали, что нельзя». → `LESSONS.md`, «Check before code».
3. **Done = evidence.** Не докладывать «готово» без доказательства: вывод теста,
   строка лога, запрос к прод-БД, скриншот. Красный тест блокирует деплой.
4. **Тест, который не видели красным, не доказывает ничего.** Показать в двух
   состояниях: убрать фикс → падает и НАЗЫВАЕТ проблему; вернуть → зелёный;
   `git diff` пуст. То же для линтеров: подложить исторический баг, показать
   exit 1. Красный тест чинить КОДОМ, а не правкой ожидания.
   → `LESSONS.md`, «Тест, который никогда не видели красным».
   - **Правило про деньги и лимиты проверять ИСПОЛНЕНИЕМ с враждебным
     payload'ом, а не поиском строки в исходнике.** Найденная в файле константа
     свидетельствует о её присутствии, а не о том, что её нельзя обойти:
     09.09 гейт «лимит пяти детей» искал текст `DEFAULT_MAX_ALIVE_CHILDREN = 5`
     и был зелёным, пока клиент поднимал предел до 20 полем в теле запроса.
     Тест обязан прислать 20 и потребовать 5.
     → `LESSONS.md`, «Тест, который читает исходник».
   - **Гейт хотя бы раз запустить так, как его запустит человек** — без своих
     `PYTHONIOENCODING` и прочих переменных. Тем же днём проверка кандидата
     падала `UnicodeEncodeError` на первой строке в обычной консоли Windows, а
     в моих прогонах была зелёной: переменная маскировала дефект ровно в том
     инструменте, который написан против масок.
5. **Ломать для проверки — только после коммита, восстанавливать из своей
   копии.** Перед тем как испортить файл ради красного прогона: закоммить
   работу. Возвращать — из сделанной копии, а НЕ через `git checkout <файл>`:
   он откатывает к последнему коммиту и не отличает подложенную поломку от
   несохранённой работы рядом. Причина: 24.08 так дважды за одну сессию снесены
   готовые правки (`STATUS.md`, потом `mobile.html`) — оба раза сразу после
   того, как проверка успешно сработала. → `LESSONS.md`, «Ломать для проверки».
6. **Судить о тесте по КОДУ ВОЗВРАТА, а не по печати.** «Зелёная» печать без
   нулевого кода — провал. Класс: **зелёный вывод ≠ зелёный результат**.
   ```bash
   python tests/test_x.py && echo PASS || echo "FAIL exit=$?"   # git-bash
   ```
   ```powershell
   python tests/test_x.py
   if ($LASTEXITCODE -eq 0) { "PASS" } else { "FAIL exit=$LASTEXITCODE" }
   ```
   Два примера не для красоты: в PowerShell 5.1 нет `&&`/`||`.
   → `LESSONS.md`, «Судить о тесте по КОДУ ВОЗВРАТА».
7. **Прод-деплой после стрима, не во время.** Идёт эфир — только хотфикс
   падающего; иначе подготовить и сказать «готово к выкату на перерыве».
   Рестарт рвёт зрителям соединение, копия мода требует закрытой игры.
8. **Фича входит — фича выходит.** На просьбу о новой механике спросить, какую
   малоиспользуемую замораживаем. Причина: разросшийся фронт — это и есть вид
   бесконтрольного «да».
9. **Заданию внешнему аудитору НЕЛЬЗЯ писать «это я уже проверил».** Можно:
   описание системы, правила, классы дефектов, карту приоритетов, свои ошибки как
   калибровку. Нельзя: «уже проверено», «не дублируй», «сюда если останется
   время». Зелёный прогон линтера — не индульгенция области. Канон —
   `docs/INDEPENDENT_AUDIT_BRIEF.md`. → `LESSONS.md`, «Заданию внешнему аудитору».
10. **Предлагать месячный аудит — ДВУХ видов, не путать.** Код-аудит читает код;
   **аудит работы** прогоняет каждую платную механику вживую и ловит то, что
   чтение не ловит: мёртвую в проде механику, дрейф кода и миграций, тихие no-op.
   Аудит работы — перед каждой подачей в Twitch. → `LESSONS.md`, «Suggest the monthly audit».
11. **Обновлять `docs/CONTEXT*.md`** после значимого изменения — это передача
   следующей сессии.
12. **НЕ ЗАПИСАНО = ЗАБЫТО.** Записывать в ту же сессию: найденную поломку,
    причину, решение владельца и его мотив, своё возражение при работе вопреки,
    класс ошибки, ручной шаг. Сводка в чате записью НЕ считается. Куда: статус
    дня → `STATUS.md`, отложенное → `DEFERRED.md`, операционное → `RUNBOOK.md`,
    правило → `CLAUDE.md`, история → `LESSONS.md`.
    → `LESSONS.md`, «НЕ ЗАПИСАНО = ЗАБЫТО».
13. **Отложенное — в `DEFERRED.md`, в ту же сессию.** Любое «потом / ждём / решим
    по данным / решили не делать» — строкой: причина + что разблокирует. Раздел
    «Решено НЕ делать» не чистится.
14. **Заканчивать сессию сводкой простым языком:** что изменилось, что где
    задеплоено, что владельцу сделать руками. Он не читает диффы — сводка и есть
    интерфейс.
15. **Пост-стрим-триаж предлагать САМ.** Видно по датам файлов, что был эфир —
    предложить разбор логов, не дожидаясь просьбы.
16. **Факт в документе имеет срок годности.** Любое «X ещё НЕ сделан» перед
    пересказом владельцу подтвердить командой. Закрыл задачу — сразу правь строку
    здесь. Лучше вообще не держать отрицательных статусов в `CLAUDE.md`.
    → `LESSONS.md`, «Факт в документе имеет срок годности».
17. **Обновлять `STATUS.md` в конце сессии** — витрина «что сейчас», 10 строк.
18. **Перед стримом — тест-план на 5 минут + preflight.** Одним сообщением список
    непроверенных мод-фиксов и `powershell -File scripts\preflight.ps1`. После
    стрима закрыть подтверждённые `bug_reports` сразу — это часть определения
    «фикс готов». → `LESSONS.md`, «Перед стримом».
19. **Рискованные бэк-правки — сначала staging** (`deploy.ps1 -Staging`, :8001,
    своя БД): миграции, меняющие данные, и переделки синка/очередей.
