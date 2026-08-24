# scripts/ — автоматизации проекта

Набор инструментов, заменяющих ручную рутину деплоя/триажа. Все скрипты
ASCII-only (PowerShell 5.1 читает .ps1 без BOM как ANSI — поэтому без кириллицы
в коде).

## deploy.ps1 — деплой одной командой
Заменяет ручной `tar → scp → ssh extract → restart` + ручной cache-bust.

```powershell
./scripts/deploy.ps1            # backend + frontend (обычный случай)
./scripts/deploy.ps1 -All       # mod + backend + frontend
./scripts/deploy.ps1 -Mod       # только собрать мод + скопировать DLL в игру
./scripts/deploy.ps1 -Backend   # только backend
./scripts/deploy.ps1 -DryRun    # показать действия, ничего не менять
```
- Frontend: авто cache-bust `viewer.js?v=` **синхронно** в extension.html и mobile.html.
- Backend/frontend: тарит папки целиком с исключениями (`*.db`, `.env`,
  `__pycache__`) — нельзя «забыть файл» и нельзя затереть прод-БД.
- Mod: `dotnet build -c Release` + копия DLL+pdb в game Modules + md5-verify.
- После пуша: restart + health-check (RUNNING + греп stderr на Traceback).
- **Не забудь закоммитить** изменённый cache-bust в html.

## lint_consistency.py — консистенси-чеки
Запускается в CI и pre-commit. Hard-fail (exit 1) на:
- рассинхрон `viewer.js?v=` между extension.html и mobile.html;
- миграция `backend/migrations/m*.py` не подключена в `main.py`;
- **использование несуществующей переменной в бэкенде** (2026-07-27) — гарантированный
  `NameError` в рантайме. `compileall` такое пропускает: синтаксис-то валидный.
  Так M97 оставил в пакете на деплой сломанный `heal-cooldown` (падал бы в 500
  на каждом открытии панели). Нужен `pyflakes`; **без него проверка мягко
  пропускается** с предупреждением, чтобы отсутствие dev-зависимости не
  блокировало коммиты.

- **частичный уникальный индекс без сторожа** (2026-07-30, `partial-lock`).
  `CREATE UNIQUE INDEX ... WHERE status='pending'` — это не порядок в таблице,
  а **замок**: пока строка висит, тот же запрос повторить нельзя. Если её никто
  не снимает по возрасту, одно потерянное событие мода блокирует зрителя
  навсегда. Класс кусал дважды: заявки о мире (июнь) и заявки на законы —
  вторые нашлись только 30.07 в ДАННЫХ прода, две штуки висели шесть дней,
  потому что сторож был написан для мира и просто забыт для законов.
  Проверка ищет индексы, чей предикат фиксирует ВРЕМЕННЫЙ статус
  (`pending`/`queued`/`requested`/…), и требует для такой таблицы код,
  истекающий строки по возрасту. Оговорка: `partial-lock-ok: <причина>`
  рядом с `CREATE INDEX`. Первый же прогон нашёл третий случай —
  очередь мини-игр (`uq_match_queue_active_user`) вообще не имела выхода
  «по времени».

Soft-warn (exit 0): дрейф manifest actions vs backend; разнобой валютных
глифов в viewer.js (⦷ vs 💎).

```bash
pip install pyflakes
python scripts/lint_consistency.py
```

## Прогоны аудита работы — доказать, что механика РАБОТАЕТ

Не код-аудит: гоняют механику на живых данных и сверяют «списалось ↔ произошло
↔ вернулось». Ловят то, чего чтение кода структурно не видит — тихий no-op,
мёртвый вход, расхождение кода с базой. Прод не трогают, работают на копии.

```bash
python scripts/local-setup.py              # 1. копия прода на ПК (вне репозитория)
# 2. поднять бэкенд: cd Расширение/backend && python main.py
python scripts/audit-rimworld-track-c.py   # трек C реестра: 6 механик RimWorld
python scripts/audit-guild-skill.py        # прокачка навыка гильдии, 29 проверок
```

Оба заканчиваются кодом возврата: **0 = все проверки сошлись**, 1 = есть
провалы. Судить по коду, а не по печати — зелёный текст при ненулевом коде уже
дважды обманывал (`CLAUDE.md` §4).

Для трека C нужна строка `TESTING_BYPASS_STREAM_LIVE=true` в `local.env`, иначе
платные ручки RimWorld закрыты проверкой «идёт ли стрим». Подробности и три
известные ловушки прогонов — `RUNBOOK.md` §10.

## check-rules-coverage.py — сокращение правил не потеряло содержания

```bash
python scripts/check-rules-coverage.py            # сравнить с HEAD~1
python scripts/check-rules-coverage.py <ревизия>  # с любой версией «до»
```

Запускать ПОСЛЕ любой переписки `CLAUDE.md` или `LESSONS.md`. Сверяет, что
каждый именованный объект (файл, функция, флаг, порог, команда) из версии «до»
жив хотя бы в одном из текущих файлов правил. 24.08 при разделении файлов
поймал реальную потерю — маркеры `CODEGRAPH_START/END`, по которым CLI
обновляет свой блок. Не ловит потерю мысли без имён: заголовки правил всё
равно смотреть глазами.

## fake-mod.py — поддельный игровой мод

Подключается вместо игры: здоровается, шлёт события, забирает команды,
подтверждает — и умеет то, чего живая игра по заказу не сделает (отказаться,
исчезнуть, подтвердить дважды).

**⚠️ Для RimWorld нужен `--rimworld-legacy`.** Без него инструмент смотрит в
generic-очередь Module API, которая для RimWorld всегда пуста, и не видит ни
одной платной покупки — «проверка» проходит, ничего не доказав. Платные ручки
RimWorld кладут команды в `rimworld_pending_commands`
(`/api/rimworld/commands` + `/ack-command`).

```bash
python scripts/fake-mod.py --channel <id> --token <t> --rimworld-legacy --refuse-all
```

## triage-crash.ps1 — разбор последнего краша
Автоматизирует ручной разбор дампа: свежая crash-папка → crash_tags →
dotnet-dump извлекает faulting managed exception + стек → греп мод-лога.

```powershell
./scripts/triage-crash.ps1            # полный (грузит dump.dmp, ~1-2 мин)
./scripts/triage-crash.ps1 -SkipDump  # быстро: только tags + мод-лог
```
Требует `dotnet tool install -g dotnet-dump`.

## CI — .github/workflows/ci.yml
На push/PR: `compileall` backend + `node --check` фронта + `lint_consistency`
(блокирующие) + pytest (информационно, пока не подтверждён зелёным).
C#-мод в CI не собирается (нужны game-DLL) — собирай локально `deploy.ps1 -Mod`.

## pre-commit — .githooks/pre-commit
Быстрый гейт перед коммитом: py_compile/node --check на застейдженных файлах +
lint_consistency. Включить один раз на клон:
```bash
git config core.hooksPath .githooks
```
Обойти при необходимости: `git commit --no-verify`.

## Бэкап БД — УЖЕ настроен (не в этой папке)
`backend/backup_db.sh` (cron 05:00, daily+weekly, sqlite `.backup` + zstd +
ротация) **плюс** in-process `backend/backup_loop.py` (каждые 6ч). Это надёжно.
**Гэп:** оффсайт. Локальные копии не спасут от смерти диска VDS. Чтобы закрыть —
задать `OFFSITE_SCP` (второй хост) или rclone/rsync в Timeweb S3 / B2.

## Что требует твоего ввода (не сделано намеренно)
- **Оффсайт-бэкап** — нужен адрес назначения (второй VDS / S3-бакет + ключи).
- **Алертинг** (падение/ошибки прода в Telegram/Discord) — нужен webhook URL;
  тогда повешу на backup-on-fail + health-ping.
