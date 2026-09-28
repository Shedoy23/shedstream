# Full audit — backend + frontend + mod (2026-05-29)

> **UPDATE 2026-05-29 — все 8 «Fix first» закрыты и задеплоены.** #1 catalog
> Phase-3 gated DEV_MODE (prod без auth → 401, проверено); #2 hello требует
> module-token (мод его шлёт по умолчанию + handshake идёт через /events, не
> /hello → нулевой риск для коннектора); #3 SyncData try/catch; #4 cap'ы
> gold(10M)/xp(1M)/tribute(±5M); #5 frontend back-off на document.hidden +
> backend read-first long-poll (BEGIN IMMEDIATE только при наличии строк);
> #6 ev.name null-guard; #7 cases.js escapeHtml (pets.js уже был escaped);
> #8 DamageHook final clamp (≥0, ≤100k, NaN-guard). Mod пересобран+DLL задеплоен,
> backend перезапущен, frontend cache-bust v=20260529b. #8 ждёт in-game verify.

> Метод: 3 параллельных deep-агента (backend / frontend / mod), все 4 оси
> (безопасность / баги / тех-долг / производительность). Находки уровня
> Critical/High я (главный) **перепроверил по коду** — калибровки помечены.
> Frontend потребовал 2 прохода: `viewer.js` = **7151 строк** (первый агент
> ошибочно прочитал только первые 1931 и решил что это весь файл — урок:
> читать большие файлы чанками с offset).

## Вердикт

Система **в заметно лучшей форме**, чем подсказывала история крашей. После
верификации **подтверждённых Critical — 0**: оба «критичных» от агентов
калиброваны до High (backend-находка = утечка low-sensitivity конфига, не PII;
mod-находка = латентный риск, без воспроизведения). Реальная работа — кластер
**High**: tenant-isolation в module-API, save-corruption риск в моде, unbounded
trust backend→mod, и **poll-амплификация** (главный риск масштаба, фронт+бек
вместе). Прайсинг на сервере, атомарный charge, EventSub HMAC, module-token
scope, XSS-escaping во фронте, particle/lifecycle в моде — всё solid.

Severity (по подсистемам, после дедупа): Backend C0·H3·M6·L4 · Frontend
C0·H3·M7·L6 · Mod C0(было1)·H4·M6·L4.

---

## Кросс-граничные темы (моя синтез-аналитика)

1. **Poll-амплификация (масштаб) — главный системный риск.** Фронт шлёт ~12-16
   запросов / 8с на зрителя (`loadBannerlordHero` + 12 sub-loader'ов + 4 быстрых
   поллера: buffs 2.5с / tournament 3с / battle 2с). Бек на каждый mod long-poll
   делает `BEGIN IMMEDIATE` (write-lock) раз в секунду на канал **даже когда нет
   действий**. На 50-100 каналах × N зрителей это доминирующая нагрузка на единый
   SQLite. → Frontend H + Backend H = **один приоритет**.
2. **Unbounded trust backend→mod.** Бек правильно энфорсит цены server-side, но
   мод применяет gold/xp/tribute из payload **без верхней границы**
   (`GiveGoldHandler`, `DiplomacyHandlers`). Это ровно то «split-brain / кто
   авторитет», что в `ARCH_DATA_OWNERSHIP.md`: мод должен re-валидировать, а не
   слепо доверять. Дёшево добавить cap'ы.
3. **Placeholder→real id backfill хрупкий.** Backend vassal placeholder-строки не
   идемпотентны (потерянный/дублированный `hero.vassal_created` → orphan занимает
   лимит). Прямое следствие dual-ownership из ARCH-1.
4. **`SyncData(Dictionary<string,int>)` — save-corruption.** В 2 behavior'ах
   (`VassalAutoFollowBehavior._vassalLastGold` — это я добавил сегодня;
   `HeroIdentityBehavior._iterationByUsername`). VassalAutoFollow.SyncData **без
   try/catch** → throw сериализатора уходит в save-pipeline.

---

## Fix first (приоритет)

| # | Severity | Что | Где | Усилие |
|---|---|---|---|---|
| 1 | High (sec) | Catalog читается cross-tenant по `?channel_id` без auth — убрать Phase-3 fallback или закрыть admin'ом | `module_api.py:481-499` | S |
| 2 | High (sec) | `module/hello` без auth, доверяет `body.channel_id` — добавить module-token + сверку channel_id | `module_api.py:82-120` | S |
| 3 | High (save) | Обернуть `VassalAutoFollowBehavior.SyncData` в try/catch; проверить round-trip `Dictionary<string,int>` (или → 2 списка) | `VassalAutoFollowBehavior.cs:74` | S |
| 4 | High (sec) | Cap'ы на gold/xp/tribute из payload в моде | `GiveGoldHandler.cs:24,54`, `DiplomacyHandlers.cs:218` | S |
| 5 | High (scale) | Poll-амплификация: батчить sub-loader'ы / поднять интервалы / back-off на `document.hidden`; бек — read-first, `BEGIN IMMEDIATE` только при наличии строк | `viewer.js:6195-6218,3267-3289` + `database.py:3547`/`module_api.py:326` | M |
| 6 | High (bug) | `renderEvents` падает на `ev.name===null` (.split) → пустеет весь список | `viewer.js:6915` | XS |
| 7 | High (sec) | Error-renderer'ы вставляют backend `message` сырым → reflected XSS | `cases.js:277`, `pets.js:408` | XS |
| 8 | High→? (crash) | DamageHook ref-мутация `Blow`/`collisionData`: добавить clamp'ы (≥0, cap, overflow guard на `(int)(x*multi)`) — дешёвая страховка против класса крашей из истории. **Нужна in-game верификация серьёзности.** | `DamageHookPatch.cs:148-181,264-271` | S |

---

## Backend (`Расширение\backend\`)

- **[High][sec] module_api.py:481-499** — catalog cross-tenant без auth (Phase-3
  `?channel_id`). ✅ верифицировано. Калибровка: агент дал Critical → **High**
  (данные = каталог/цены, не PII/не points/не write). Fix: убрать fallback.
- **[High][sec] module_api.py:82-120** — `hello` без auth, спуфит «online»/session
  side-effects для любого канала. ✅ верифицировано. Fix: module-token + сверка.
- **[High][perf] database.py:3547 / module_api.py:326** — per-second long-poll
  открывает `BEGIN IMMEDIATE` даже на 0 строк → write-contention на единый SQLite.
- **[High/Med][debt+sec] admin.py:185-357** — raw `aiosqlite` + un-scoped (без
  channel_id) запросы на viewers/inventory/pawns (8 нарушений DB-дисциплины);
  admin-gated, но cross-tenant data-integrity hazard. Из прошлого аудита, не пофикшено.
- **[Med] auth.py:36-44** — DEV_MODE bypass по localhost-IP; опасно если утечёт в прод за прокси.
- **[Med] module_api.py:126,717** — per-channel dedup-ring / power-event буферы не чистятся при offline → медленный рост памяти.
- **[Med] bannerlord_vassals.py:152-178** — placeholder vassal не идемпотентен (backfill race → orphan занимает лимит 5).
- **[Med] admin.py:234-264** — adjust_points read/charge на 2-3 разных коннекшнах (TOCTOU).
- **[Med] bannerlord.py:1261-1325** — pre-validation открывает доп. db-коннекшны до charge-TX (pool pressure при спаме).
- **[Med] viewer.py:290-317** — `/api/user/level/{username}` читает произвольный username, дефолт-канал без JWT (info-disclosure).
- **[Low]** ADMIN_PASSWORD печатается в лог (dependencies.py:507); `SELECT 1` на каждом release (db_pool.py:116); `is_channel_registered` fail-open до init кэша; O(n) reverse-lookup login→id.
- **Solid:** server-side prices + role-multipliers (ToS-ok), атомарный single-shot charge с rollback, EventSub HMAC+replay+dedup, module-token issue/verify с `compare_digest`, sub-route'ы scoped по `channel_id AND owner_username`, reset-endpoint (session-gated, whitelist).

## Frontend (`Расширение\frontend\`, оба прохода viewer.js 1-7151 + модули)

- **[High][sec] cases.js:277, pets.js:408** — `renderError(msg)` вставляет backend `message` сырым → reflected XSS если бек эхо-ит user-ввод. Fix: `escapeHtml(msg)`.
- **[High][bug] viewer.js:6915** — `renderEvents` падает на `ev.name.split` если name=null → весь список пустеет. Fix: `(ev.name||'')`.
- **[High][perf] viewer.js:6195-6218, 3267-3289** — poll-амплификация (см. кросс-тему #1).
- **[Med][sec] viewer.js:6645 `showConfirm`, 5102 `_bnrShowSimpleModal`** — title/message в `innerHTML` сырыми. Сегодня все callers escape'ят, но латентный foot-gun. Fix: escape внутри или задокументировать контракт.
- **[Med][sec]** pets.js emoji-поля (156-203), `renderLevelBar` title (982), tournament `class_key` (5674), raw `data-*` ids (pets/dice/duels) — сырые, но источники — backend-энумы/числа (низкий риск). Fix: escape для единообразия.
- **[Med][bug] viewer.js:6892-6917** event-cooldown тик ре-рендерит весь список раз/сек 5 минут.
- **[Med][debt]** монолит 7151 строк; ~15× копипаст fetch-boilerplate; неравномерный error-handling sub-loader'ов (часть keep-last-render «v6», часть всё ещё `innerHTML=''` → мерцают: diplo/ransom/heirs/family/vassals/caravan-rescues).
- **[Low]** bare `setInterval` в обход `safeInterval` (1112, 527) → не чистится на teardown; `_cachedUserPoints` vs `window.userPoints` рассинхрон; equipment slot/culture без escape.
- **XSS-итог:** ~70 `innerHTML` sink'ов суммарно; подавляющее большинство escape'ят. Реально чинить ~8 (выше). **0 Critical XSS, токен не утекает** (только `X-Twitch-JWT` header; `encodeURIComponent` на единственном query-user-value; postMessage origin allowlist; `rel=noopener`; нет eval).
- **v7-рефактор верифицирован корректным:** stable skeleton + изолированный `#bnr-pane-hero-stats`, бинды только при реальном repaint — listener-стэкинга нет.

## Mod (`BannerlordLink\src\`)

- **[High→потенц. Critical][crash] DamageHookPatch.cs:148-181,264-271** — ref-мутация `Blow`/`collisionData` без clamp/overflow guard на rage-множителе и armor-absorb; тот самый класс пути из истории нативных крашей (counter-blow уже выключен, но ref-мутация осталась). Калибровка: агент дал Critical → **High + needs in-game verification**. Fix: clamp'ы.
- **[High][save] VassalAutoFollowBehavior.cs:74 (+HeroIdentityBehavior.cs:46)** — `SyncData(Dictionary<string,int>)` без try/catch → риск save-corruption. (Это включает мой сегодняшний `_vassalLastGold`.) Fix: try/catch + проверить round-trip.
- **[High][sec] GiveGoldHandler.cs:24,54, DiplomacyHandlers.cs:218** — unbounded gold/xp/tribute из payload (см. кросс-тему #2). Fix: cap'ы.
- **[High][perf] PowersMissionBehavior.cs:162-227** — O(agents) LINQ-сканы + string-parse per call в slow-tick (DoT/FindAgentByUsername); в 1000-agent осаде = фриз. Fix: индекс username→Agent на OnAgentBuild.
- **[High][thread] ActionPoller.cs:84-85** — `Mission.Current` читается из poll-треда (нарушение main-thread контракта; torn read на mission-transition). Fix: volatile `_inMission` флаг с main-thread.
- **[Med]** MainThreadDispatcher drain-cap 32/frame (лаг под burst); `KillRewardBehavior._partyRestores` static List без lock; BackendClient детектит успех через `Contains("\"ok\":true")` вместо парсинга; BackendConfig не валидирует https + самописный JSON-парсер; ActionPoller idempotency-ring O(n) cleanup; `new Random()` per call + GetHashCode spawn-offset.
- **[Low]** дублированная hero-resolution в ~15 handler'ах; dead `IsAlreadySpawned`; `obj/Release/*.cs` закоммичен (надо gitignore); разбросанные magic numbers.
- **Solid:** Harmony bool-возвраты fail-open (безопасно), graceful `TargetMethods()`, reflection-guard'ы, `AgentPfx`/`HeroPfxBehaviour` lifecycle (idempotent Stop, cleanup на OnAgentDeleted/OnEndMission, ToList-снэпшот) — particle-leak закрыт; poller dedup + OperationCanceled re-throw; нет TLS-disable / secret-logging.

---

## Примечание по достоверности
- Backend C1→H1, Mod C1→H1: обе «critical» от агентов я калибровал вниз после
  проверки кода (catalog = low-sensitivity; DamageHook = латентно, без repro).
- Frontend: первый агент промахнулся по длине файла; пере-аудит второй половины
  сделан отдельным проходом — покрытие полное (1-7151).
- Все High с пометкой «needs verification» (DamageHook) требуют подтверждения
  в игре, прежде чем считать их подтверждёнными.
