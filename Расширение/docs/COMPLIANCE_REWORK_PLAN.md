# Compliance Rework Plan

> **Версия:** 1.0  
> **Дата:** 2026-05-10  
> **Авторитетные правила Twitch на момент написания:** Extension Guidelines & Policies (dev.twitch.tv/docs/extensions/guidelines-and-policies/), Bits AUP, Channel Points AUP, Community Guidelines + январь-2026 enforcement update.  
> **Базовый аудит inventory:** см. секцию 2 ниже.

## 0. Mission & TL;DR

**Цель:** перевести extension с серых/красных gambling-механик на compliant-эквиваленты, сохранив engagement-loop'ы. Готовиться к первому submission в Twitch review с полностью compliant-кодом.

**Что вырезаем:** casino (слоты/джекпот/риск/фриспины), рулетка-режим в event-системе, ставки в дуэлях, крафт, рынок P2P, конвертация ₽→крустики, P2P transfer крустиков, family financial pool.

**Что добавляем:** система кейсов (4 тира фиксированной награды), гильдии (база без бустов), аукционы переделанные в голосование за действие стримера, дуэли v2 с matchmaking без ставок.

**Что оставляем:** quests, watch-time, chat-bonus, drops (теперь выпадает кейс а не item), achievements, streaks, sезонные награды дуэлей, marriage как чисто social.

**Сроки:** 6 фаз, 10-15 сессий с кодом + дизайн UI/UX. Прод не трогаем во время работы (стрима нет → юзеры не лезут).

---

## 1. Ключевые правила Twitch — выдержки

Полный референс — в чате с агентом fetch'нувшим источники. Здесь — то что прямо влияет на наши решения.

### Что прямо запрещено (CRITICAL)

| Правило | Источник | Применимо к нам |
|---|---|---|
| Gambling activities с monetary reward | Ext. Guidelines §6.2.3 | Casino, рулетка, дуэли-ставки |
| Wagering/betting на outcomes beyond user's control | §6.2.6 | Casino, рулетка, дуэли-ставки |
| Bits → loot box с unknown/random items (даже если бесплатно по контенту) | §6.2.4 | Применимо если когда-нибудь введём Bits — кейсы только за активность/CP |
| Bits → items specified by broadcaster/users ad-hoc | §6.2.8 | Запрещает Bits-аукционы; не для нас если Bits не используем |
| Items за money или commerce instruments (не loyalty-points/Bits) | §5.2 | Запрещает /api/donate (₽→предмет) |
| Loot boxes с monetary value contents | §5.3 | Кейсы должны содержать только items без денежной ценности |
| Extension не должен быть кассой для charity/donations | §5.4 | Запрещает /api/donate целиком |
| Off-Twitch action incentivisation как основной use case | §4.5 | Запрещает «потрать на DonationAlerts → получи валюту» |
| NFT в extension | §4.11 | Не наш кейс |
| Bits — нельзя продавать/обменивать/переводить между юзерами | Bits AUP | Не наш кейс (Bits не используем) |
| Channel Points — нельзя продавать/переводить/обменивать на cash/goods | CP AUP | Применимо если интегрируем CP redemption — нельзя их P2P делать |
| **2026 Bits-tightening:** запрет off-platform value exchange / proxy-for-money | Bits AUP 2026-01 | Закрывает обходные схемы через сторонние сервисы донатов |
| Запрет лексики «cheering / donation / spend / buy / insert» при описании Bits | §6.4, §6.5 | Не используем Bits — но дух распространяется на нашу валюту |

### Серые зоны (требуют conservative interpretation)

| Зона | Ситуация | Conservative выбор |
|---|---|---|
| **Internal currency P2P transfer** | Прямого запрета нет в guidelines (запрещены только Bits/CP P2P) | **Убрать.** Дух 2026-tightening против off-platform value exchange. |
| **Marriage с shared currency** | Social-feature OK; но `family_balance` + withdraw = de-facto P2P transfer | **Убрать financial-часть.** Оставить marriage как social: статус, joint streak, эмодзи. |
| **Multiplier к скорости накопления** | Прямого запрета нет; §6.1.3 даже разрешает «enrich gameplay» | **Не делаем сейчас.** В будущем гильдии могут получить multiplier при условии что доступен всем гильдиям равно. |
| **Slot-style UI** даже без monetary reward | §5.3 разрешает RNG без ценности; но Community Guidelines + 2026 enforcement расширили gambling-категорию на skin gambling и free-play версии гэмблинг-сайтов | **Убрать reels/spin/jackpot UI.** Кейсы — простая анимация раскрытия сундука. |
| **Auction за internal currency** | §5.2 формально разрешает items за loyalty-points | **OK** при условии что items предопределены extension'ом, не user-supplied |
| **Конвертация watch-time → Bits-equivalent** | Если internal currency выглядит как «Bits proxy», 2026-tightening применим по аналогии | **Не публиковать exchange rate** «X крустиков = Y Bits» |

### Что РАЗРЕШЕНО подтверждённо

- Free RNG-награды за активность без monetary value (§5.3 spirit)
- Items за loyalty-points (§5.2) — наша валюта = loyalty-points
- Quests, achievements, streaks, leaderboards — детерминированные награды за активность
- Auctions за internal currency на extension-defined items/actions (по §5.2 + §6.1.4 voting analogy)
- Channel Points integration для broadcaster experiences (§6.1.1)

---

## 2. Verdict-таблица 16 механик кода

Источник: cross-reference inventory кода (отдельный отчёт от Explore-агента 2026-05-10) × правила выше.

| # | Механика | Verdict | Файлы | Что делаем |
|---|---|---|---|---|
| 1 | Старое казино `/casino/bet` | 🔴 REMOVE | `routes/casino.py`, `bot_core.casino_bet` | Удалить |
| 2 | Слоты + jackpot | 🔴 REMOVE | `routes/casino.py` (slots/double/jackpot), `casino.py` целиком | Удалить, заменить на кейсы |
| 3 | Фриспины | 🔴 REMOVE | `routes/casino.py` (slots/freespin), `free_spins_daily` table | Удалить |
| 4 | Риск-игра | 🔴 REMOVE | `routes/casino.py` (slots/double), `_pending_doubles` | Удалить |
| 5 | Дуэли со ставкой | 🔴 REMOVE WAGER | `routes/duel.py` create/accept | Убрать `body.amount`, transfer'ы, оставить ELO + matchmaking |
| 6.a | Рулетка-режим | 🔴 REMOVE | `event_manager.py` branch `if type == "roulette"`, `_build_event` `random.choices` | Удалить branch |
| 6.b | Аукцион-режим | 🟡 REWORK | `event_manager.py`, `routes/event.py` | Переделать в голосование за действие стримера |
| 7 | Крафт | 🔴 REMOVE | `routes/craft.py`, `craft_stats` table | Удалить |
| 8 | Family +15💎/мин | 🟡 REWORK | `routes/marriage.py`, `marriages.family_balance`, `run_family_income` в `main.py` | Убрать financial pool, оставить social |
| 9 | Рынок P2P | 🔴 REMOVE | `routes/market.py`, `market_listings` table, `frontend/market.js`, `frontend/shop.js`(?) | Удалить |
| 10 | Промокоды | ✅ KEEP | `routes/promo.py` | Только убедиться что награды compliant (без бустов) |
| 11 | Донат `/api/donate` | 🔴 REMOVE | endpoint в `routes/admin.py` или `misc.py` | Удалить |
| 12 | P2P transfer | 🔴 REMOVE | `/api/points/transfer` endpoint | Удалить |
| 13 | Quests | ✅ KEEP | `routes/viewer.py`, `bot_core._update_quest_progress` | Без изменений |
| 14 | Drops loop | 🟡 REWORK | `bot_core._process_drop`, `DROP_ITEMS` | Выпадает кейс (по rarity weights) вместо item |
| 15 | Watch-time / chat-bonus | ✅ KEEP | `bot_core._reward_points`, `compute_chat_bonus` | Без изменений |
| 16 | Admin grants | 🟡 AUDIT | `routes/admin.py` | Убрать `/api/donate`, оставить остальное (broadcaster-control разрешён §7.4) |

**Итого:**
- 🔴 8 механик целиком под нож
- 🟡 4 механики переделать
- ✅ 4 механики оставить как есть

---

## 3. Phase 0 — Lexicon scrub (preliminary)

Запрещённые слова в коде/UI: ~100 хитов. Но удаление файлов casino.js/casino.py закрывает ~70% автоматически. Остаток — точечные правки.

### План Phase 0

- Удалить `frontend/casino.js` целиком (Phase 1 действие — но сразу убирает ~80 хитов)
- Удалить `backend/casino.py` целиком + `routes/casino.py` (~30 хитов)
- В `frontend/overlay.html`: удалить блок `.card-jackpot`, `.jackpot-amount`, `.jackpot-mega` (~10 хитов) — заменить на drop/case-card
- В `frontend/family.js`: переименовать type `"roulette"` → `"vote"` (после Phase 4) (~3 хита)
- В `backend/event_manager.py`: удалить branch `if type == "roulette"`, `EVENT_TYPES` сократить до `auction`/`vote` (~8 хитов)
- В `backend/models.py`: удалить класс `BetRequest` (1 хит)
- В `frontend/extension.html`: удалить кнопки/секцию казино (~5 хитов), добавить секцию «Кейсы»

### Acceptance criteria Phase 0
- `grep -ri "casino\|slot\|jackpot\|bet\|spin\|рулетк\|gamble" frontend/` → 0 хитов
- `grep -ri "casino\|slot\|jackpot" backend/` → 0 хитов (кроме комментариев в migrations и историчекских коммитах)

---

## 4. Phase 1 — Removal pass

Атомарная чистка всего что под 🔴 REMOVE. Делается одним коммитом + одной DB-миграцией M8.

### 4.1 Backend файлы — удалить целиком

```
backend/casino.py
backend/routes/casino.py
backend/routes/craft.py
backend/routes/market.py
```

### 4.2 Backend файлы — частичные правки

| Файл | Что вырезать |
|---|---|
| `routes/duel.py` | Поля `amount` в моделях, transfer-логика (loser→winner крустики), валидация `min 50💎`. Оставить ELO/sезоны/leaderboard. |
| `routes/marriage.py` | Endpoint'ы `/withdraw`, `family_balance` в response'ах, divorce-cost логику если завязана на pool |
| `routes/admin.py` | Endpoint `/api/donate` (если он там) |
| `routes/misc.py` | `/api/points/transfer` endpoint, `/api/donate` если там |
| `event_manager.py` | branch `if event["type"] == "roulette"` в `end_event`, `EVENT_TYPES` урезать, рандом выбора типа |
| `bot_core.py` | Удалить `casino_bet`, `casino_total_bets`, `casino_cooldown_*`, `last_raffle` (если относится к казино). `CASINO_CONFIG` import. |
| `main.py` | `run_family_income` — удалить целиком loop. Включения casino router'а — удалить. |
| `config.py` | `CASINO_CONFIG` целиком, `EVENT_TYPES` урезать |
| `models.py` | `BetRequest`, `DuelRequest.amount` |
| `database.py` | Helpers для market/casino/craft (`db.add_market_listing`, etc.) |

### 4.3 Frontend файлы — удалить целиком

```
frontend/casino.js
frontend/market.js
frontend/shop.js (если содержит rynok-логику; проверить при удалении)
```

### 4.4 Frontend файлы — частичные правки

| Файл | Что вырезать |
|---|---|
| `extension.html` / `mobile.html` | Кнопки/секции «Казино», «Рынок», «Крафт», «Перевод», «Донат» |
| `overlay.html` | Jackpot CSS-блок, jackpot события |
| `duels.js` | Поля для ставки `amount`, оставить move-выбор + matchmaking placeholder (на Phase 5 переделать) |
| `family.js` | Withdraw form, family_balance display. Оставить marriage status / proposals / joint streak (когда добавим) |
| `viewer.js` | Если есть craft/market UI |

### 4.5 Database — миграция M8 (`m8_compliance_cleanup.py`)

```sql
-- Backup taken via backup_db.sh before applying

-- 1. Drop tables под нож
DROP TABLE IF EXISTS casino_settings;
DROP TABLE IF EXISTS free_spins_daily;
DROP TABLE IF EXISTS pending_doubles;     -- in-memory обычно, но если есть
DROP TABLE IF EXISTS market_listings;
DROP TABLE IF EXISTS craft_stats;

-- 2. Cleanup family financial: refund family_balance в личные крустики ДО drop колонки
WITH refund_pairs AS (
    SELECT id, channel_id, user1, user2, family_balance
    FROM marriages
    WHERE family_balance > 0 AND divorced_at IS NULL
)
UPDATE viewers SET points = points + (
    SELECT COALESCE(SUM(family_balance / 2), 0)
    FROM refund_pairs
    WHERE refund_pairs.channel_id = viewers.channel_id
      AND viewers.username IN (refund_pairs.user1, refund_pairs.user2)
);
ALTER TABLE marriages DROP COLUMN family_balance;

-- 3. Cleanup duel state: refund pending_duels.amount создателям
UPDATE viewers SET points = points + (
    SELECT COALESCE(SUM(pd.amount), 0)
    FROM pending_duels pd
    WHERE pd.channel_id = viewers.channel_id
      AND pd.creator = viewers.username
);
DELETE FROM pending_duels;
ALTER TABLE pending_duels DROP COLUMN amount;

-- 4. Audit log что сделано
INSERT INTO migrations_applied (name, applied_at) VALUES ('M8_compliance_cleanup', datetime('now'));
```

**Важно:** SQLite до 3.35 не поддерживает `DROP COLUMN`. Если у нас старая SQLite — придётся пересоздавать таблицу через rename + recreate + insert. Проверить `sqlite3 --version` на проде перед миграцией.

### 4.6 Acceptance criteria Phase 1

- Все routes регистрируются без import error'ов
- Existing isolation tests (56/56 pass) — продолжают проходить
- Smoke endpoint check: `/v1/modules`, `/streamer`, `/api/viewer/streak/{u}`, `/api/duel/leaderboard` — все 200
- DB migration applied + idempotent
- Frontend renders без console errors (visual check)
- Lexicon scrub passes (см. Phase 0 criteria)

### 4.7 Rollback план

Если что-то сломается:
1. Backup БД сделан перед M8 → restore через `backup_db.sh restore <path>`
2. Code revert через `git revert <commit-removal>`
3. Refund tables: cmрут к `viewers.points` нельзя реверснуть автоматически — но рефанды задокументированы в audit log

---

## 5. Phase 2 — Кейсы (новая система)

### 5.1 Дизайн

**4 тира** с фиксированной наградой крустиков:

| Тир | Награда | Источники получения |
|---|---|---|
| Обычный | 1 000 💎 | Дневные квесты (random watchtime/chat) |
| Редкий | 10 000 💎 | Streak 10 дней, weekly milestone |
| Эпик | 100 000 💎 | Watch 100h, monthly milestone |
| Легендарный | 500 000 💎 | Sезонные milestone (раз в 3 мес) |

**Drops loop переделка** (Phase 6 параллельно):
- 25% шанс drop'а каждые 20 мин (как сейчас)
- Tier weights: обычный 70%, редкий 25%, эпик 4%, легендарный 1%
- Выпадает кейс в инвентарь юзера

**UI принципы:**
- Превью пула наград (1k/10k/100k/500k) видно ДО открытия — compliant с §5.3 spirit
- Анимация раскрытия — простая (сундук открывается, цифра появляется)
- НИКАКИХ reels/spin/slot-style анимаций
- Цветовая дифференциация по тиру (common серый / rare синий / epic фиолетовый / legendary золотой)

### 5.2 База данных — миграция M9 (`m9_cases.py`)

```sql
CREATE TABLE IF NOT EXISTS cases (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id      INTEGER NOT NULL,
    username        TEXT NOT NULL,
    tier            TEXT NOT NULL CHECK (tier IN ('common', 'rare', 'epic', 'legendary')),
    source          TEXT NOT NULL,              -- 'quest', 'streak', 'watch_milestone', 'season', 'drop'
    awarded_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    opened_at       TIMESTAMP,                  -- NULL = не открыт
    reward_points   INTEGER,                    -- заполняется при open (фиксированно по тиру, но record для истории)
    FOREIGN KEY (channel_id) REFERENCES channels(channel_id)
);

CREATE INDEX idx_cases_user ON cases(channel_id, username, opened_at);
CREATE INDEX idx_cases_unopened ON cases(channel_id, username) WHERE opened_at IS NULL;
```

### 5.3 Endpoints

```
GET  /api/viewer/cases              — список кейсов юзера (открытые/закрытые)
POST /api/viewer/case/open          — открыть кейс по id
GET  /api/case/preview/{tier}       — preview наград тира (для UI до open)
POST /api/admin/case/grant          — выдать кейс юзеру (для тестов/комплиментов)
```

### 5.4 Backend triggers (где автоматически выдаются)

В `bot_core._update_quest_progress` после complete_quest:
```python
if quest_type in DAILY_QUESTS:
    await db.grant_case(username, channel_id, tier='common', source='quest')
```

В `record_viewer_attendance` (streak triggers):
```python
if streak == 10:
    await db.grant_case(username, channel_id, tier='rare', source='streak')
```

В `bot_core._reward_points` watch_hours milestone:
```python
total_hours = await db.get_total_watch_hours(...)
if total_hours >= 100 and not already_granted:
    await db.grant_case(username, channel_id, tier='epic', source='watch_100h')
```

В `_process_drop` (Phase 6):
```python
tier = random.choices(['common', 'rare', 'epic', 'legendary'],
                      weights=[70, 25, 4, 1])[0]
await db.grant_case(lucky, channel_id, tier=tier, source='drop')
```

### 5.5 Frontend — новый файл `frontend/cases.js`

- Сетка кейсов юзера (закрытые сверху, открытые снизу)
- Click на закрытый → анимация раскрытия → `+N💎` появляется
- Звук открытия (опционально, off by default per §2.4)
- Preview-tooltip при hover показывает фиксированную награду

### 5.6 Acceptance criteria Phase 2

- Tests: open case adds correct points, idempotent (один кейс = одно открытие)
- Tests: case grant per quest/streak/milestone triggers без дублей
- UI: 0 lexicon hits в `cases.js`
- Smoke: `/api/viewer/cases` возвращает список, `/case/open` атомарно меняет состояние

---

## 6. Phase 3 — Гильдии (база)

### 6.1 Дизайн

**Гильдия base v1:**
- Имя (3-30 chars), tagline (≤80 chars)
- Master (создатель, может kick)
- Members (max 50)
- Balance (общий пул крустиков от участников)
- Skills v1 — placeholder (структура есть, концретные skills доработаем потом)

**Создание гильдии:** стоимость **100 000 крустиков** с master'а (sink крустиков).

**Перки гильдии (compliant):**
- Косметика: баннер, эмблема (default свежие, custom — Phase 7+ когда нарисуем), цвет имени в чате (опционально)
- Кланчат (отдельный канал в overlay, видно только участникам)
- Лидерборд гильдий (top by balance / top by members)
- В будущем — клановые челленджи / турниры

**НЕТ бустов накопления** (Вариант 2a из обсуждений).

### 6.2 База данных — миграция M10 (`m10_guilds.py`)

```sql
CREATE TABLE IF NOT EXISTS guilds (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id      INTEGER NOT NULL,
    name            TEXT NOT NULL,
    tagline         TEXT,
    master_username TEXT NOT NULL,
    balance         INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (channel_id, name)
);

CREATE TABLE IF NOT EXISTS guild_members (
    guild_id    INTEGER NOT NULL,
    channel_id  INTEGER NOT NULL,
    username    TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('master', 'officer', 'member')),
    joined_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, username),
    FOREIGN KEY (guild_id) REFERENCES guilds(id)
);

CREATE TABLE IF NOT EXISTS guild_skills (
    guild_id    INTEGER NOT NULL,
    skill_key   TEXT NOT NULL,
    level       INTEGER NOT NULL DEFAULT 0,
    exp         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, skill_key)
);

CREATE TABLE IF NOT EXISTS guild_contributions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id        INTEGER NOT NULL,
    channel_id      INTEGER NOT NULL,
    username        TEXT NOT NULL,
    amount          INTEGER NOT NULL,
    contributed_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_guilds_channel ON guilds(channel_id, balance DESC);
CREATE INDEX idx_members_user ON guild_members(channel_id, username);
CREATE INDEX idx_contribs_guild ON guild_contributions(guild_id, contributed_at DESC);
```

**Constraint per юзер:** один юзер в одной гильдии на одном канале (через UNIQUE на `guild_members.username`-per-channel — обеспечить через index или check trigger).

### 6.3 Endpoints

```
POST  /api/guild/create              — name, tagline (cost 100k)
POST  /api/guild/join                — guild_id
POST  /api/guild/leave
POST  /api/guild/contribute          — amount (sink крустиков в guild balance)
GET   /api/guild/{id}                — info: name, tagline, balance, members, skills
GET   /api/guild/list                — top by balance, paginated
GET   /api/guild/my                  — текущая гильдия юзера
POST  /api/guild/kick                — master only, target_username
POST  /api/guild/upgrade-skill       — master only, skill_key (cost из guild balance)
GET   /api/guild/leaderboard         — top guilds
```

### 6.4 Frontend — новый файл `frontend/guild.js`

- Browse: список гильдий канала с фильтром по имени
- Join modal: подтверждение
- My guild: дашборд (balance, members count, my role, skills tree)
- Master controls: kick member, upgrade skill, edit tagline
- Кланчат widget (минимальный, scope для Phase 3.1+)

### 6.5 Skills initial — placeholder

В migration создаём 2 placeholder-skills:
```python
DEFAULT_GUILD_SKILLS = {
    'extra_member_slots': {'max_level': 5, 'cost_per_level': [50000, 100000, 200000, 400000, 800000]},
    'cosmetic_banner_unlock': {'max_level': 1, 'cost_per_level': [200000]},
}
```

Skills logic — на Phase 3.1+ (после base работает). Сейчас просто структура есть.

### 6.6 Acceptance criteria Phase 3

- Create guild снимает 100k у master'а атомарно
- Join при наличии в другой гильдии — error
- Contribute идёт в balance, юзер видит свою сумму contributions
- Master может kick других, не себя
- Tests: race condition защита (двойной create с тем же name → error)
- Smoke: GET endpoints возвращают валидный JSON

---

## 7. Phase 4 — Аукционы → голосование за действие стримера

### 7.1 Дизайн (твоя идея 4)

Полный rework `event_manager.py`:

**Что было:**
- Копилка от user-contributions
- Когда полная → стартует ивент типа `roulette` или `auction`
- Юзеры ставят крустиками
- Победитель получает item

**Что будет:**
- Копилка от **пассивной активности** (1 минута просмотра = 1 unit, 1 чат-сообщение = 5 units, drop = 50 units)
- Когда полная → стартует **голосование**
- Стример заранее настраивает «варианты действий» через дашборд (что играть / какой стиль / какую еду заказать на стрим)
- Юзеры вкидывают крустики на свой выбранный вариант
- В конце таймера побеждает вариант с **max суммой ставок крустиков**
- Refund НЕ делается (это collective vote, не commerce)
- Prize: стример выполняет выбранное действие

**Compliance анализ:**
- ✅ §5.2 (items за loyalty-points) не применяется — нет item'а
- ✅ §6.2.6 (wagering) не применяется — outcome определяется юзерами, не "beyond their control"
- ✅ §6.1.4 (voting activities) — прямо разрешено даже за Bits, наш case — за internal currency
- ✅ §5.3 (loot box monetary value) не применяется — нет рандома, детерминированный max-bid winner

### 7.2 База данных — миграция M11

```sql
-- Текущая event-инфра в основном in-memory (event_manager.py state)
-- Persist для voting events:

CREATE TABLE IF NOT EXISTS voting_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id      INTEGER NOT NULL,
    started_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ends_at         TIMESTAMP NOT NULL,
    finished        INTEGER NOT NULL DEFAULT 0,
    winning_option  TEXT,
    total_pool      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS voting_options (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        INTEGER NOT NULL,
    option_key      TEXT NOT NULL,
    label           TEXT NOT NULL,
    description     TEXT,
    pool            INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (event_id) REFERENCES voting_events(id)
);

CREATE TABLE IF NOT EXISTS voting_bids (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        INTEGER NOT NULL,
    option_id       INTEGER NOT NULL,
    channel_id      INTEGER NOT NULL,
    username        TEXT NOT NULL,
    amount          INTEGER NOT NULL,
    placed_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_voting_events_active ON voting_events(channel_id, finished, ends_at);
CREATE INDEX idx_voting_bids_event ON voting_bids(event_id, option_id);

-- Streamer's настроенные шаблоны опций (for re-use)
CREATE TABLE IF NOT EXISTS streamer_voting_templates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id      INTEGER NOT NULL,
    template_name   TEXT NOT NULL,
    options_json    TEXT NOT NULL,             -- [{key, label, description}, ...]
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 7.3 Endpoints (re-use старого `routes/event.py`, переписать логику)

```
GET   /api/event/status                         — текущий voting event + копилка
POST  /api/event/bid                            — option_id + amount (без contribute теперь — копилка автоматическая)

# Streamer config
GET   /api/streamer/voting-templates            — список шаблонов
POST  /api/streamer/voting-template/create      — name + options_json
DELETE /api/streamer/voting-template/{id}
POST  /api/streamer/voting/start                — start event with template_id (если стример хочет force-start вне copilkа-trigger'а)
```

### 7.4 Backend — `event_manager.py` rework

- `event_pool` теперь наполняется автоматически из `_reward_points` (watch + chat + drop)
- `_build_event` берёт активный template канала (если нет — событие не стартует)
- `place_bid` принимает `option_id`
- `end_event` определяет winner = max(option.pool), записывает в БД, шлёт chat-сообщение

### 7.5 Frontend — `frontend/family.js` (где сейчас рулекцион) либо новый `event.js`

- Visualization: progressbar копилки, варианты с текущим pool каждого, кнопка bid
- При победе варианта — модальное окно «победил вариант X»
- Стример видит дашборд templates (отдельная страница `streamer-config.html`?)

### 7.6 Acceptance criteria Phase 4

- Копилка наполняется без user `/contribute` endpoint'ов (полностью автоматически)
- Bid атомарно списывает крустики и кредитит option pool
- end_event находит correct winner = max bid, refund NOT происходит
- Streamer без template — событие не стартует (грейсфул error)
- Lexicon: 0 хитов «рулетка/roulette»

---

## 8. Phase 5 — Дуэли v2 (matchmaking, no wager)

### 8.1 Дизайн

- **Убрать ставку:** `body.amount` удалён, transfer крустиков от loser к winner — нет
- **Добавить matchmaking:** «найти противника» вместо «принять конкретную дуэль»
- **Matchmaking логика:**
  - Юзер встаёт в очередь, указывая желаемый ELO-spread (default ±100)
  - Backend каждые 5 сек пытается матчить пары (ближайшие по ELO)
  - Match найден → создаётся room, оба уведомляются (long-poll или WebSocket)
  - В room оба делают move (RPS) → определяется winner
  - ELO обновляется, sезонная статистика
- **Lock от двойного принятия** — уже есть в коде (`status pending→accepting`)
- **Sезонные награды** — оставляем (уже compliant: PRIZES для top-3 в конце сезона)

### 8.2 База данных — миграция M12

```sql
-- Старая pending_duels — переходит в queue
ALTER TABLE pending_duels DROP COLUMN amount;       -- уже сделано в M8
ALTER TABLE pending_duels ADD COLUMN status TEXT NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'matched', 'in_room', 'finished'));
ALTER TABLE pending_duels ADD COLUMN matched_with TEXT;
ALTER TABLE pending_duels ADD COLUMN matched_at TIMESTAMP;
ALTER TABLE pending_duels ADD COLUMN room_id TEXT;

-- Index для matchmaking lookup
CREATE INDEX IF NOT EXISTS idx_duels_matchmaking
    ON pending_duels(channel_id, status, matched_at)
    WHERE status = 'queued';
```

ELO для matchmaking — берём из `duel_stats.elo` (already есть).

### 8.3 Endpoints (rework `routes/duel.py`)

```
POST /api/duel/queue                        — встать в очередь (опц. ELO-spread)
GET  /api/duel/queue/status                 — мой match найден? room_id?
POST /api/duel/queue/cancel                 — выйти из очереди
POST /api/duel/room/{room_id}/move          — отправить move в комнате
GET  /api/duel/room/{room_id}/state         — состояние матча (poll)
GET  /api/duel/leaderboard                  — без изменений
GET  /api/duel/my-stats                     — без изменений
```

### 8.4 Backend — matchmaking loop

В `bot_core.py` или отдельный `matchmaking.py`:
```python
async def matchmaking_loop(self):
    while self.running:
        await asyncio.sleep(5)
        for channel in await self.db.list_channels():
            await self._match_pairs(channel['channel_id'])

async def _match_pairs(self, channel_id):
    queued = await self.db.get_queued_duels(channel_id)  # status='queued'
    # Sort by ELO
    queued.sort(key=lambda x: x['elo'])
    # Pair consecutive ones if ELO-spread satisfied
    i = 0
    while i + 1 < len(queued):
        a, b = queued[i], queued[i + 1]
        if abs(a['elo'] - b['elo']) <= max(a['spread'], b['spread']):
            await self.db.match_duels(a['username'], b['username'], channel_id)
            i += 2
        else:
            i += 1
```

### 8.5 Frontend — `frontend/duels.js` rework

- Кнопка «Найти противника» вместо «Создать дуэль»
- Loading state «Поиск... ETA ~30s» с текущим положением в очереди
- Cancel button
- Match found → modal с RPS-кнопками (rock/scissors/paper)
- Result modal с ELO change

### 8.6 Acceptance criteria Phase 5

- Tests: queue → match → move → result, no points transfer
- Tests: parallel queue requests от одного юзера → idempotent (один queue entry)
- Tests: ELO-spread соблюдается
- Smoke: leaderboard работает, sезоны автоматически закрываются

---

## 9. Phase 6 — Drops loop переделка

### 9.1 Минимальные изменения в `bot_core._process_drop`

```python
# Вместо DROP_ITEMS:
DROP_CASE_TIERS = [
    ('common', 70),
    ('rare', 25),
    ('epic', 4),
    ('legendary', 1),
]

async def _process_drop(self, channel_id):
    cid = resolve_channel_id(channel_id)
    if not await self._is_stream_live(channel_id=cid):
        return
    if random.random() > DROP_CHANCE:
        return

    # ... existing active-viewer selection ...
    if not active:
        return
    lucky = random.choice(active)

    # NEW: drop = case вместо item
    tier = random.choices(
        [t[0] for t in DROP_CASE_TIERS],
        weights=[t[1] for t in DROP_CASE_TIERS]
    )[0]
    await self.db.grant_case(lucky, channel_id=cid, tier=tier, source='drop')
    await self.send_message(
        f"🎁 @{lucky} получил {TIER_EMOJI[tier]} {TIER_NAME[tier]} кейс! "
        f"Открой через расширение!", channel_id=cid)
```

### 9.2 Acceptance criteria Phase 6

- Drop теперь даёт case, не item (в `cases` table запись появляется)
- Distribution тиров примерно 70/25/4/1 на длинном sample
- Chat-уведомление работает per-channel

---

## 10. Order of operations

| # | Phase | Зависимости | Рекомендуется делать когда |
|---|---|---|---|
| 0 | Lexicon scrub | Нет | Параллельно с Phase 1 (auto-resolved при удалении файлов) |
| 1 | Removal pass | Нет | **ПЕРВОЙ** — расчищает базу. Атомарный коммит. |
| 2 | Кейсы (новая система) | Phase 1 | После Phase 1 |
| 3 | Гильдии (база) | Phase 1 | После Phase 1, можно параллельно с Phase 2 (разные подсистемы) |
| 4 | Аукционы → голосование | Phase 1, частично event_manager.py остался | После Phase 1 |
| 5 | Дуэли v2 | Phase 1 (ставки убраны) | После Phase 1 |
| 6 | Drops в кейсы | Phase 2 (cases table должна существовать) | После Phase 2 |

**Параллельность:** Phases 2, 3, 4, 5 могут идти параллельно/в любом порядке после Phase 1. Phase 6 требует Phase 2.

**Рекомендуемая последовательность сессий:**
1. Phase 0 + Phase 1 (одна большая сессия — removal + миграция M8) — 1 день
2. Phase 2 (кейсы) — 2-3 сессии
3. Phase 6 (drops в кейсы) — 0.5 сессии (короткое)
4. Phase 5 (дуэли v2) — 1-2 сессии
5. Phase 3 (гильдии) — 2-3 сессии
6. Phase 4 (голосование) — 2 сессии
7. UI polish + testing — 1-2 сессии
8. **Pre-review session:** прогон всего против compliance checklist — 1 сессия

Всего: ~10-15 сессий в зависимости от глубины полировки.

---

## 11. Acceptance criteria для review submission

Прежде чем подавать на ревью Twitch:

### Hard requirements (CRITICAL)
- [ ] 0 lexicon hits для `casino|slot|jackpot|bet|spin|roulette|gamble|wager` в frontend и backend (кроме комментариев в migrations)
- [ ] 0 endpoints типа `/api/casino/*`, `/api/craft/*`, `/api/market/*`, `/api/donate`, `/api/points/transfer`
- [ ] Все механики проходят 3-вопрос тест из COMPLIANCE_AND_ARCHITECTURE.md §5.1: consideration / chance / prize — никогда все три "yes"
- [ ] Все loot-box-like механики (кейсы) выдаются ТОЛЬКО за активность, никогда за валюту
- [ ] Description расширения в Twitch-store accurate описывает все фичи (§4.2)
- [ ] Twitch Extension Helper — first script в HTML (§2.9)
- [ ] No iframes (§2.2), no Flash (§2.1), audio off by default (§2.4)
- [ ] No NFT (§4.11)

### Soft requirements (полировка)
- [ ] Тестовый канал live при review (стрим 24/7)
- [ ] Review-promo-code дающий стартовый набор кейсов для reviewer'а
- [ ] Боты-имитаторы для демо multiplayer-фич (дуэли, гильдии)
- [ ] Демо-режим с сокращёнными cooldown'ами на тест-канале
- [ ] Видео-демонстрация работы (3-5 мин)
- [ ] Notes для ревьюера в submission form

---

## 12. Open questions / future work

### Что отложено осознанно
- **Косметика контента** (Phase 7+): когда нарисуем — fill кейсы (рандомная косметика по §5.3) и гильдийные баннеры/эмблемы
- **Гильдийские skills** (Phase 3.1+): после base работает — конкретные branches (extra_member_slots, cosmetic unlocks, possibly умеренные social-бонусы)
- **Battle pass / sезоны** (Phase 8+): прогресс-дорожка за активность с косметикой/кейсами по уровням
- **Турниры между гильдиями** (после Phase 3.1)

### Открытые вопросы для дальнейшего обсуждения
1. **Marriage v2:** что конкретно остаётся после удаления financial?
   - Joint streak (счётчик дней когда оба зрителя одновременно)?
   - Cohabitation badge / rank (символический)?
   - Joint лидерборд пар?
   - Решение: при дизайне Phase 1 (когда удалим financial) — обсудим что добавить взамен.

2. **Kanal Points integration**: scopes объявлены (`channel:read:redemptions`), но не реализовано. Хотим ли потом подключить (например — стример настраивает «redeem 5000 CP за обычный кейс»)? Это §6.1.1 compliant, но требует EventSub setup и UI в дашборде стримера.

3. **Бан-листы / антиабуз:** при review reviewer'ы смотрят на anti-abuse механики. У нас есть chat-bonus антифрод (M7), drops blacklist. Достаточно ли для review? Возможно нужны:
   - Rate limit на /api/duel/queue (anti-bot)
   - Detection «свежесозданный аккаунт» (по watch-history)
   - Soft cap на максимальные накопления (твой §10.1)

4. **B2B-tier'ы стримера** (free/Pro/Premium/VIP из COMPLIANCE_AND_ARCHITECTURE.md §7.4):
   - Сейчас: tier хранится в `channels.tier`, но никаких проверок per-tier нет
   - Концепт: после первого ревью добавить tier-gate на features (например, гильдии — только Pro+)
   - Compliance: tier'ы не дают game-преимуществ юзерам канала (DSA OK, разработчик собирает деньги вне Twitch payment system)
   - Решение: на потом, когда запустимся в test-канал

5. **Аукционы — refund?** Сейчас в дизайне Phase 4 написано «refund НЕ делается». Для voting это OK (voting за действие — все участники получили результат). Но для редких сценариев (стример отменяет ивент / технический сбой) нужна стример-vето опция (§2.5 рекомендует).

---

## 13. Документ-references

- `Расширение/docs/PROJECT_PLAYBOOK.md` — продуктовый playbook (review prep, метрики, B2B, общий roadmap)
- `Расширение/docs/ARCHITECTURE.md` — общая архитектура, Bug 4 fix history
- `C:\Users\Edward\Desktop\work\memory\COMPLIANCE_AND_ARCHITECTURE.md` — оригинальный compliance-doc (по памяти)
- Authoritative Twitch rules — реальные источники:
  - https://dev.twitch.tv/docs/extensions/guidelines-and-policies/
  - https://legal.twitch.com/legal/bits-acceptable-use
  - https://legal.twitch.com/en/legal/channel-points-acceptable-use-policy/
  - https://safety.twitch.tv/s/article/Community-Guidelines
  - https://dev.twitch.tv/docs/extensions/monetization/

---

**Подпись:** этот план зафиксирован 2026-05-10 после полной инвентаризации кода и валидации против актуальных правил Twitch (включая 2026 enforcement update). Изменения в плане — только через явное обсуждение со стримером.
