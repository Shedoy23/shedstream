# Twitch Extension — Main Context (chat handoff)

**Назначение:** для **общей** части расширения. Для конкретных модулей —
см. `CONTEXT_RIMWORLD.md` (legacy game), `CONTEXT_BANNERLORD.md`
(active live game, sprint 5.27v), `CONTEXT_PETS_V3.md` (in-progress pixel-art overhaul, paused awaiting PixelLab subscription).

**Last updated:** 2026-07-29 (аудит РАБОТЫ по реестру: треки A и D закрыты,
C прогнан на 6/8, B ждёт живой игры; 5 багрепортов гейта починены; блокер —
красный тест кассы)

---

## TL;DR

Twitch Extension для viewer engagement. **Multi-tenant** FastAPI backend +
SQLite + twitchio bot + vanilla JS frontend. Live на `twitch.tv/shedoy23`,
прод на Timeweb VPS `31.130.132.224`, домен `shedoy23.ru`.

Архитектура — **platform с pluggable game modules**:

- **Core (game-agnostic):**
  - balance + кассы (alpha/beta/gamma + jackpot)
  - гильдии (12 видов с уникальными бонусами)
  - голосования (RUS/EN/DE/FR/ES/IT/JP/KR/ZH локализация)
  - matchmaking (TicTacToe 4×4 + Dice 3-round + Duels с ELO + RPS)
  - **pets v2** (universal с overlay items, walking on screen)
  - **TTS** ("озвучить сообщение" через server-side gTTS)
  - Twitch chat hooks (EventSub realtime)
  - channel-points integration
  - TG notifications (stream.online → Telegram)
  - dev login + OAuth
- **Game modules:**
  - **RimWorld** (legacy + Phase 7 refactor, отдельный handoff `CONTEXT_RIMWORLD.md`)
  - **Bannerlord** (active, sprint 5.27v — отдельный handoff `CONTEXT_BANNERLORD.md`)

---

## Аудит РАБОТЫ (не код-аудит) — состояние на 2026-07-29

Планка 0.0.2 от владельца: «весь функционал ядра, Bannerlord и RimWorld работает
как задумано». Перечень того, что именно должно работать, и рабочий лист —
**`AUDIT_REGISTER_0.0.2.md`**. Гейт заморозки описан в `CHANGELOG_0.0.2.md`.

| Трек | Что это | Состояние |
|---|---|---|
| **A. Ядро** | озвучка, питомцы, кейсы, гильдии, голосования, промокоды, квесты, мини-игры | ✅ закрыт целиком |
| **B. Bannerlord** | 9 групп действий | ⬜ **не начат — нужна живая игра** |
| **C. RimWorld** | 8 платных механик | ✅ 6 из 8 прогоном; гены/черты и ивенты пусты |
| **D. Следы вырезанных механик** | задние двери, мёртвый код | ✅ закрыт |

**Чем это отличается от код-аудита и почему нужно оба.** Код-аудит читает код и
структурно НЕ видит: механику, мёртвую в проде; расхождение кода с миграцией;
тихий no-op платного действия. Всё это ловится только прогоном на живых данных.
За 29.07 так нашлись: мёртвый вход у аукциона, копилка в памяти процесса,
незакрытые сезоны, инструмент проверки RimWorld, смотревший не в ту очередь.

**Инструменты (прод не трогают):**
- `python scripts/local-setup.py` — копия прода на ПК из вчерашнего бэкапа;
- `python scripts/audit-rimworld-track-c.py` — трек C целиком (exit 0);
- `python scripts/audit-guild-skill.py` — прокачка навыка гильдии, 29 проверок;
- `python scripts/fake-mod.py --rimworld-legacy` — поддельный мод; **без флага
  не видит платных команд RimWorld**, они идут в старую очередь;
- `python scripts/audit_dead_code.py` — кандидаты в мёртвый код (отчёт, не гейт).

**✅ Блокер выката снят 30.07:** тест кассы `test_bannerlord_buy_action.py`
зелёный (71 проверка). Действие для проверки кассы вынесено в константу
`CHARGE_ACTION` — следующая уборка из продажи не положит тест молча.

### Аудит ПО СПЕКЕ (`AUDIT_SPEC.md`) — отдельный трек, состояние на 30.07

| Раздел | Состояние |
|---|---|
| §1 касса Bannerlord | ✅ закрыт, найдена цена из тела запроса (2 действия) |
| §2 возвраты | ✅ закрыт, конкурентные отказы доказаны тестом |
| §3 записи авансом | ✅ закрыт, найден живой замок на заявках о законах |
| §5 граница доверия к моду | ✅ закрыт, найден пакет событий без потолка |
| §8 кулдауны и лимиты | ⚠️ частично — гонку воспроизвести не удалось |
| §4, §6, §7, §9–§17 | не начаты; следующие по цене ошибки — §9 и §11 |

**Правило, выведенное этим треком и стоящее дороже отдельных находок:** зелёный
тест — это утверждение о тесте, а не о коде, пока не показано, что он краснеет.
Дважды за день тест давал успех и оставался зелёным при СНЯТОЙ защите — то есть
не измерял ничего. Проверка на чувствительность обязательна там, где вывод идёт
в отчёт.

**Аудит имеет три исхода, а не два:** «держится, вот доказательство», «сломано,
вот сценарий» и «не смог проверить, вот что пробовал и что закроет вопрос».
Третий — самый бесполезный для отчёта и самый честный; подменять его первым
означает обесценить весь аудит.

**Независимая проверка сторонней моделью** — часть гейта. Пакет готов:
`INDEPENDENT_AUDIT_BRIEF.md` (правила, приоритеты, мои ошибки как калибровка) +
`AUDIT_SPEC.md` (17 блоков «инвариант / как ломается здесь / где смотреть / чем
проверить», с якорем-коммитом). Все числа обоих документов сверены с кодом
машинно. **В задании нельзя писать «это я уже проверил, сюда не смотри»** — в
том числе числом: «сторожей шесть» закрывало область не хуже прямого запрета.

## Текущий статус

### 🆕 2026-06-14 — Бот приветствует подписчиков И фолловеров в чате

Бот пишет **текстовое** приветствие в чат при подписке и при фолове (только
текст, без крустиков/динаров/наград — ToS §5.2, sub-бонусы давно вырезаны).
Реализация:
- **EventSub** (`eventsub.py`): 4 новых типа в `PHASE_A_SUBSCRIPTIONS` +
  хендлеры — `channel.subscribe` (новый саб; `is_gift=true` пропускаем),
  `channel.subscription.message` (ресаб, с числом месяцев),
  `channel.subscription.gift` (ОДНО спасибо дарителю, не по получателям —
  анти-спам на бомбах подарков), `channel.follow` v2 (новый фоллов).
- **Фоллов-анти-флуд:** sliding-window rate-limit (`_FOLLOW_GREET_MAX_PER_WINDOW`
  =8 / 60с на канал). Фолловы спамнее сабов (фолоу-боты); превышение лимита
  логируется и скипается, чтобы бот не зафлудил чат и не словил спам-таймаут.
- **m74** `channel_greet_settings` (per-channel, `sub_enabled`+`follow_enabled`,
  оба default ON, раздельные) + `db.get_channel_greet_settings` /
  `set_channel_greet_setting(kind)`.
- **Toggle** (стример-self-serve): `GET /api/streamer/greet` → `{sub, follow}`;
  `POST` body `{kind: 'sub'|'follow', enabled}` (session-cookie scoped). UI-кнопок
  в дашборде пока НЕТ — фича работает по умолчанию ON, выключается через endpoint.
- **Требует scopes** `channel:read:subscriptions` (сабы) + `moderator:read:followers`
  (фоллов, channel.follow v2 — `moderator_user_id`=broadcaster в условии). Оба
  в `config.py`. Старый OAuth-токен без них → Twitch вернёт 403 при регистрации
  (логируется, остальные подписки не ломает) → стримеру нужен **re-auth**.
  EventSub перерегистрируется при рестарте бэка.

### 🆕 2026-06-14 — Статистика watch-стриков (серии просмотров)

Бот **молча** (НЕ в чат) собирает все watch-стрики зрителей («смотрит 50-й
стрим подряд») в лидерборд лояльности для стримера. Пассивная аналитика —
зрителям наград/геймплея не даёт (Twitch ToS OK).
- **EventSub** `channel.chat.notification` v1 (`eventsub.py`) — «общая труба»
  чат-нотисов; хендлер фильтрует **только** `notice_type='watch_streak'`,
  остальное (сабы/рейды) игнор. Из payload берём `chatter_user_login` +
  `watch_streak.streak_count` + `channel_points_awarded`.
- **m75** `watch_streaks` (upsert по channel_id+username): `streak_count`
  (текущая серия), `best_streak` (максимум за всё время), `total_points`
  (сумма начисленных Twitch баллов). `db.record_watch_streak` /
  `get_watch_streaks`.
- **Просмотр** (стример-self-serve): `GET /api/streamer/watch-streaks?limit=N`
  → топ по текущей серии. UI-карточки в дашборде пока НЕТ.
- **Требует scope** `user:read:chat` (broadcaster читает свой чат; condition
  `broadcaster_user_id`+`user_id`=bid). В `config.py`. Тот же **re-auth**, что
  и для сабов/фоллоу — одним заходом. Стрик-данные появятся только для тех, у
  кого Twitch включил watch-стрики на канале (настройка Channel Points).

### ✅ Закрыто (с момента 5.16 update)

**UI/UX redesign:**
- **Sprint 5.19** — главная страница «Бот» переработана в семантические
  секции (Бот / Магазин / Канал / Bannerlord-modal-button)
- **Mobile parity** — `mobile.html` повторяет `extension.html`, единый viewer.js

**Pets (Sprint 5.21–5.22):**
- M29 schema v2: face/aura/body slots + svg_path + scarf→body migration
- M30: catalog +15 items (новые шапки, очки, маски, кулоны)
- M31/M32: deprecated + hard-deleted 4 misfit items
- SVG creature + CSS pet-stage component (universal, accepts variants)
- Overlay walking pets: gulять по всей ширине, sway animation, **slower** walk,
  full username (без сокращения)
- Background теперь перекрашивает creature body (через CSS variables),
  убрали отдельный bg-emoji слой
- Aura: 6 particles вокруг pet

**TTS (Sprint 5.23):**
- M33: tts_messages table
- M34: tts.audio_data BLOB column
- Server-side gTTS (Google Translate TTS) → MP3 BLOB
  (Web Speech API не работал в OBS browser source — пришлось переехать)
- Frontend modal + 3-я карточка в Канал секции
- Overlay: audio play через Audio() element (OBS требует "Control audio via OBS")

**Mini-games rework (Sprint 5.24):**
- **5.24a Dice:** 3 раунда + re-roll одного кубика + 10s timer per action,
  auto-expire на /poll endpoint (lazy expiration)
- **5.24b Duels:** matchmaking queue + best-of-3 + 10s timer
  (raньше был instant выбор хода, теперь арена)
- **5.24c TicTacToe:** 4×4 grid + best-of-3 + 10s timer
- Result screens теперь не auto-close (polling-based)
- Dice timer fix: deadline_at refresh на каждое action (раньше показывал 0с)

**Season prizes (Sprint 5.25):**
- Dice/duel/RPS/TTT все на 2-week сезонах
- ELO start 1000 (раньше 1100), prize gate ≥1100
- Prizes: 300k/200k/100k (top-3)

**Marriage fix (Sprint 5.20):**
- M8 dropped `family_balance` column, но marriage.py всё ещё INSERT'ил → 500
- Fix: removed family_balance из 2 INSERTs
- Added /api/marriage/reject endpoint + UI кнопка отклонения

**Bannerlord — отдельный сектор (см. CONTEXT_BANNERLORD.md):**
- 40+ sprints (5.0 → 5.27v) — full BLT-style game module
- Family system (gender swap / marriage to NPC / children + family tree)
- BLT × 0.5 kill rewards + level scaling + kill streaks
- Hideout support, clan upgrades, agent rename, MapEventEnded cleanup
- 28+ action handlers, 12+ API endpoints, миграции M14-M36

### 🔴 Pending для Twitch submission

1. Description в Twitch Extension Store → «multi-game platform»
2. Frontend zip → upload в Twitch Hosted Test → Released
3. Submission notes — `docs/REVIEW_SUBMISSION.md`

### 🟢 Intentional DEFERRED (после launch)

- [BITS-SIG] real Twitch Bits transaction JWT signature verify
- [BROADCASTER-JWT] streamer toggle через role='broadcaster'
- Generic UI renderer (overkill пока для 2 модулей)
- TTL для queued module_actions (сейчас лежат вечно если mod не applied,
  нет refund при skip/expire)

---

## Stack

- **Backend:** Python FastAPI + aiosqlite (DBPool) + twitchio bot
- **Frontend:** Vanilla JS (`extension.html`, `mobile.html`,
  `overlay.html`, `config.html`) — **no build step** (Twitch extension constraint),
  cache-bust через `?v=YYYYMMDDx` суффикс в HTML script tags
- **Game mods:** RimWorld C# (Harmony patches), Bannerlord C# (.NET net472)
- **БД:** SQLite + WAL, **36 migrations** (M1-M36) — pets/tts/clan_upgrades/family
- **Auth:** Twitch Extension JWT (HS256, `TWITCH_EXTENSION_SECRET`)
- **Hosting:** supervisor → uvicorn :8000, nginx reverse proxy
- **TG notifier:** stream-online → Telegram channel (см. `TELEGRAM_SETUP.md`)
- **Realtime:** EventSub webhook → `backend/eventsub.py`
  (stream.online/offline, channel_points)
- **TTS:** gTTS Python lib (server-side MP3 BLOB), frontend Audio() в overlay

---

## Server / deploy

- **Host:** `root@31.130.132.224` (Timeweb VPS, SSH key auth)
- **Path:** `/root/twitch-extension/{backend,frontend,admin,docs,backups,logs}`
- **Supervisor:** `/etc/supervisor/conf.d/twitchbot.conf`
- **Logs:**
  - Supervisor stdout/stderr: `supervisorctl tail -200 twitchbot stdout`
  - Files: `/var/log/twitchbot.{out,err}.log` (logrotate daily/10M/7d)
- **DB:** `/root/twitch-extension/backend/viewers.db` (SQLite WAL)
- **Admin panel:** `https://shedoy23.ru/admin` (HTTP Basic, creds в .env)
- **Dev login:** `https://shedoy23.ru/dev` (Twitch OAuth, persistent cookie)

### Deploy (no CI, manual tar-pipe SSH)

```bash
# Common pattern для любых файлов
cd Расширение
tar -cf /tmp/sprintX.tar backend/<files> frontend/<files>
scp /tmp/sprintX.tar root@31.130.132.224:/tmp/
ssh root@31.130.132.224 'cd /root/twitch-extension && tar -xf /tmp/sprintX.tar \
  && supervisorctl restart twitchbot'

# Frontend cache-bust (после изменения .js)
cd Расширение/frontend
sed -i 's/viewer.js?v=20260521u/viewer.js?v=20260521v/g' extension.html mobile.html
# bump pet-stage.js / pets.js аналогично если меняли
```

### Build mod (Bannerlord)

```bash
cd "/x/SteamLibrary/.../Shedoy23.BannerlordLink/src"
"/c/Program Files/dotnet/dotnet" build BannerlordLink.csproj -c Release
# Output: ../bin/Win64_Shipping_Client/BannerlordLink.dll
# ВАЖНО: закрыть Bannerlord перед build, иначе DLL залочен (compile проходит,
#        но copy fails — игрок не получает обновлённую логику)
```

---

## Ключевые файлы

| Где | Что |
|---|---|
| `Расширение/docs/CONTEXT.md` | **этот файл** — общий handoff |
| `Расширение/docs/CONTEXT_BANNERLORD.md` | Bannerlord module handoff (sprint 5.27v) |
| `Расширение/docs/CONTEXT_RIMWORLD.md` | RimWorld module handoff |
| `Расширение/docs/PROJECT_PLAYBOOK.md` | Roadmap, метрики, B2B |
| `Расширение/docs/ARCHITECTURE.md` | Multi-tenant, layers |
| `Расширение/docs/COMPLIANCE_REWORK_PLAN.md` | 6 фаз compliance |
| `Расширение/docs/REVIEW_SUBMISSION.md` | Submission notes для Twitch reviewer'а |
| `Расширение/docs/TELEGRAM_SETUP.md` | TG-нотификации |
| `Расширение/docs/MODULE_API.md` | Game Bridge SDK |
| `Расширение/docs/SECURITY_AUDIT_2026-04-30.md` | 13 CRITICAL fixes audit |
| `Расширение/backend/main.py` | FastAPI app + startup + migrations |
| `Расширение/backend/bot_core.py` | IRC bot + reward loops + matchmaking |
| `Расширение/backend/database.py` | Все SQL + helpers |
| `Расширение/backend/eventsub.py` | EventSub generic dispatcher |
| `Расширение/backend/routes/` | Routes по features (pets/cases/guilds/voting/dice/duel/tts/bannerlord/...) |
| `Расширение/backend/migrations/m1-m36_*.py` | Schema migrations (36 штук) |
| `Расширение/backend/routes/dev_login.py` | /dev OAuth flow |
| `Расширение/backend/notifications.py` | TG sendMessage helper |
| `Расширение/backend/modules/{rimworld,bannerlord}/` | Module adapters + manifests |
| `Расширение/frontend/extension.html` | Главный UI (desktop Twitch panel) |
| `Расширение/frontend/mobile.html` | Mobile-parity copy |
| `Расширение/frontend/viewer.js` | ~3700 строк всей логики |
| `Расширение/frontend/pet-stage.js` | Universal pet SVG component |
| `Расширение/frontend/overlay.html` | OBS browser source overlay |
| `BannerlordLink/` | Git mirror Bannerlord mod (sync via cp) |

---

## Module API (брыдж к игровым модулям)

Backend-mod коммуникация через generic Module API
(`backend/routes/module_api.py`):

1. **Mod → Backend events:** `POST /v1/module/<id>/event`
   (player.state_update, player.died, hero.attribute_changed, etc.)
2. **Backend → Mod actions:** `GET /v1/module/<id>/actions?since=<id>`
   (long-poll 25s, batch up to 50)
3. **Mod → Backend ack:** `POST /v1/module/<id>/ack` (success/fail)

Storage: `module_actions` table (M5) с lifecycle queued/dispatched/acked/failed.
JWT module_id + channel_id binding.

**ВАЖНО:** действия в queue хранятся **forever** (нет TTL/cleanup). Если стример
давно не заходил, накопится много actions → при запуске mod применит batch.
Это is known tech debt (см. CONTEXT_BANNERLORD.md §Open).

---

## Тестирование

### Live test без стрима
1. https://shedoy23.ru/dev → login через Twitch
2. После OAuth → click «Open extension preview»
3. Открывается extension.html с твоим JWT — все фичи работают

Альтернатива: `curl -u admin:pass /api/admin/dev/jwt?username=X&minutes=60`
→ preview_url для конкретного юзера.

### Bypass для отсутствия стрима
```bash
ssh root@31.130.132.224 'sed -i "/TESTING_BYPASS_STREAM_LIVE/d" .env;
                        echo "TESTING_BYPASS_STREAM_LIVE=true" >> .env;
                        supervisorctl restart twitchbot'
```
Не забыть выключить после теста.

### Test counts (последний run)
- 1088/1088 isolation tests (`test_multi_tenant_isolation.py`)
- 34/34 EventSub security tests

---

## Quick verification

```bash
# Server status
ssh root@31.130.132.224 'supervisorctl status twitchbot && df -h /root | head -2'

# Свежие логи
ssh root@31.130.132.224 'supervisorctl tail -100 twitchbot stdout'

# Migrations applied
ssh root@31.130.132.224 'sqlite3 /root/twitch-extension/backend/viewers.db \
  "SELECT name FROM migrations_applied ORDER BY applied_at DESC LIMIT 10"'

# Preview URL
curl -u shedoy23:33133313 "https://shedoy23.ru/api/admin/dev/jwt?username=shedoy23"

# Bannerlord-specific
ssh root@31.130.132.224 'sqlite3 /root/twitch-extension/backend/viewers.db \
  "SELECT count(*) FROM bannerlord_heroes WHERE channel_id=98319857"'

# Pet stats
ssh root@31.130.132.224 'sqlite3 /root/twitch-extension/backend/viewers.db \
  "SELECT count(*), avg(level) FROM pets"'

# Action queue size (сколько pending'ов)
ssh root@31.130.132.224 'sqlite3 /root/twitch-extension/backend/viewers.db \
  "SELECT module_id, status, count(*) FROM module_actions GROUP BY module_id, status"'
```

---

## Open вопросы / next steps

**🔴 Sprint 5.2 — Compliance rebrand перед public Twitch release:**
- Audit Bannerlord mod (class_keys / power_keys / numeric values vs BLT LGPL)
- NOTICE.md
- Extension submission notes update

**🟠 Features в очереди:**
- Auto-summon 30 мин подписка (Bannerlord — viewer покупает window)
- Tavern summon (BLT `SummonInLocation`)
- Hero relations system
- AI Advisors (Trade Advisor MVP rule-based)
- Whitelist auto-add из channel point redemption

**🟡 Tech debt:**
- TTL для `module_actions` queue (сейчас лежат вечно)
- Refund при skipped action (viewer оплатил но runtime check failed)
- `bannerlord_buy_action` 750-строчный — dispatch table
- 20+ Bannerlord handlers share username-extract → `ActionHandlerBase`
- Test 19 extend для новых fields (focus / attributes / family_info)

---

## Recent gotchas / lessons (с 5.16)

1. **Case-mismatch dictionary lookups** между Python (lowercase) и JS
   (PascalCase) — тихая боль. Lesson: normalize at the boundary
   (см. Bannerlord 5.27v: `_to_pascal` в response).
2. **OBS browser source НЕ поддерживает** Web Speech API — TTS пришлось
   реализовать как server-side gTTS MP3 BLOB. OBS audio source toggle
   "Control audio via OBS" обязательно ON.
3. **JavaScript TDZ** при `const` объявлениях ниже use site — поймали
   при TTS overlay refactor. Подняли const'ы выше if/else блока.
4. **OAuth state TTL** — preview JWT может протухнуть на длинной сессии,
   debug через DevTools Network tab (status 401).
5. **TaleWorlds save format не backwards-compatible** на minor engine
   bumps (1.3.15 → 1.4.5). Steam auto-update должен быть OFF на streaming PC.
   Также community mods (Diplomacy, ButterLib, etc.) ломаются при upgrade.
6. **Lazy expiration vs background loop:** для timers в dice/duel/TTT —
   проще expire on poll (clean state when client asks) чем держать
   asyncio.Tasks (race conditions, leaks).
7. **DLL lock при build (Bannerlord)** — если игра запущена, copy в bin/
   fails (Watchdog process holds file). Compile проходит, DLL не обновляется
   silently. Lesson: закрыть игру перед `dotnet build`.

---

## Repo

- **GitHub:** `Shedoy23/shedstream` (private monorepo)
- **Branch:** `claude/hopeful-agnesi-ea9afe` (long-lived feature branch)
- **HEAD:** см. `git log --oneline -1`

---

## Module Sub-Contexts

Для **детальной** работы по конкретному модулю — открой соответствующий handoff:

- **Bannerlord** → `Расширение/docs/CONTEXT_BANNERLORD.md`
  (sprint 5.27v, BLT-aligned, family system, all 28+ handlers и т.д.)
- **RimWorld** → `Расширение/docs/CONTEXT_RIMWORLD.md`
  (legacy + Phase 7 refactor, отдельный handoff)

В этом файле — **общая** information о Twitch extension as a platform.
Глубокие детали game-modules вынесены отдельно для compact context.

---

**Использование для нового чата:** скинуть этот файл + сказать
*«Читай CONTEXT.md, продолжаем работу над main extension»*.
Если нужна работа по конкретной игре — также скинуть `CONTEXT_BANNERLORD.md`
или `CONTEXT_RIMWORLD.md`.
