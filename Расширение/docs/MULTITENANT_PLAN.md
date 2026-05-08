# Multi-tenant рефакторинг — план

**Status:** M3.0.1 deployed (2026-05-04). Дальше M4 (channels registry + admin-UI lite + EventSub auto-register).
**Context:** [PLATFORM_VISION.md](../../PLATFORM_VISION.md) этап 2 / [MODULE_API.md](MODULE_API.md) §13.

Цель: один backend обслуживает N стримеров. Каждый запрос знает «для какого стримера» — данные изолированы по `channel_id` (Twitch broadcaster user_id).

---

## M0 — что готово

- ✅ **WAL включён** на проде (`journal_mode=wal`, `synchronous=2`, `busy_timeout=5000`).
- ✅ **Бэкапы настроены:** `backend/backup_db.sh` + cron `0 5 * * *`. Хранение: 14 ежедневных + 8 еженедельных. Атомарный `.backup` через SQLite (не corrupt'ит на живой БД). Сжатие zstd-19 даёт ~7x: 9.4 MB → 1.3 MB.
- ✅ **Discovery audit** завершён — таблицы расклассифицированы, миграции спланированы.

---

## §A — Классификация таблиц

**TENANT (нужна `channel_id`):** 27 таблиц
```
viewers, purchase_counters, inventory, quests, drops, marriages, marriage_proposals,
activity_stats, chat_stats, market_listings, craft_stats, casino_settings,
free_spins_daily, duel_stats, duel_seasons, pending_duels, stream_attendance,
stream_streaks, stream_sessions, user_achievements, promo_uses, channel_points_log,
streak_rewards, rimworld_pawns, rimworld_pawn_equipment, rimworld_pawn_skills,
rimworld_pawn_hediffs, rimworld_pawn_traits, rimworld_pawn_genes, rimworld_colonists,
rimworld_skills, rimworld_pending_commands, rimworld_heal_cooldowns, rimworld_event_catalog
```
Включая ревизии после агента: `stream_sessions` (стрим конкретного стримера), `rimworld_pending_commands` (cmd_id per-streamer), `rimworld_event_catalog` (стример сам публикует свой каталог событий через Module API).

**GLOBAL (без channel_id):** 4 таблицы
```
items                  — справочник предметов (id, name, emoji, value)
achievements           — определения ачивок (key, name, reward)
rimworld_catalog       — defNames RimWorld мода
shop_catalog           — каталог магазина (если универсален; иначе TENANT)
```

**SPLIT (часть GLOBAL, часть TENANT):**
- `user_achievements` (анлоки) — TENANT. Зритель смотрит 5 каналов → может получить «10 часов» 5 раз.
- `promo_uses` (применения) — TENANT. Один промокод может быть валиден на нескольких каналах.

**LOOKUP (привязано к Twitch user, не к стримеру):**
- `twitch_ids` — маппинг Twitch user_id → login. Глобально.

---

## §B — Решения по двойственным таблицам

| Таблица | Что решено | Почему |
|---|---|---|
| `user_achievements` | TENANT (per-channel) | Достижения per-канал. Watching 10h на канале А ≠ 10h глобально. |
| `promo_uses` | TENANT | Один промокод (`SPRING2026`) можно ввести на разных каналах независимо. |
| `promocodes` | TENANT в новой модели | Каждый стример сам создаёт промокоды для своих зрителей. |
| `rimworld_catalog` | GLOBAL | Это статика мода, не кастомизируется. |
| `shop_catalog` | TENANT + **session-scoped** | Очищается на каждом `session-start` от мода. См. §H. |
| `rimworld_event_catalog` | TENANT + **session-scoped** | То же — кэш активной игровой сессии, не accumulating. |
| `achievements` | GLOBAL для MVP | Кастомные ачивки per-channel — будущая фича. |
| ~~`purchase_counters`~~ → `rimworld_purchase_counters` | **pawn-scoped** через FK CASCADE | Привязан к `rimworld_pawns.id`. Пешка умерла → счётчик обнулился. Это RimWorld-specific. |

---

## §C — Миграция данных (DDL)

Прод-база содержит ~110 000 строк одного стримера (`broadcaster_id=98319857`). Backfill — установить этот ID для всех существующих строк.

**Процесс:**
1. `ALTER TABLE` для добавления колонки с DEFAULT (быстро)
2. Пересоздать таблицы где меняется UNIQUE/PRIMARY KEY (8 таблиц, требуется CREATE+INSERT+RENAME)
3. Создать композитные индексы

**Таблицы требующие пересоздания** (UNIQUE/PK меняется):

| Таблица | Старый ключ | Новый ключ |
|---|---|---|
| `viewers` | `username UNIQUE` | `(channel_id, username) UNIQUE` |
| `rimworld_pawns` | `username UNIQUE` | `(channel_id, username) UNIQUE` |
| `duel_stats` | `username PRIMARY KEY` | `(channel_id, username) PK` |
| `stream_streaks` | `username PRIMARY KEY` | `(channel_id, username) PK` |
| `casino_settings` | `key PRIMARY KEY` | `(channel_id, key) PK` |
| `free_spins_daily` | `username PRIMARY KEY` | `(channel_id, username) PK` |
| `craft_stats` | `(username, item_type) PK` | `(channel_id, username, item_type) PK` |
| `purchase_counters` | `(username, category) PK` | `(channel_id, username, category) PK` |

**Шаблон пересоздания** (для каждой):
```sql
BEGIN TRANSACTION;
CREATE TABLE viewers_new (...поля + channel_id INTEGER NOT NULL DEFAULT 98319857...);
INSERT INTO viewers_new SELECT *, 98319857 FROM viewers;
DROP TABLE viewers;
ALTER TABLE viewers_new RENAME TO viewers;
COMMIT;
```

**Индексы (после миграции):**
```sql
CREATE INDEX idx_activity_stats_channel_username_date
  ON activity_stats(channel_id, username, date(created_at));
CREATE INDEX idx_chat_stats_channel_username_date
  ON chat_stats(channel_id, username, date(created_at));
CREATE INDEX idx_market_listings_channel_seller
  ON market_listings(channel_id, seller);
CREATE INDEX idx_stream_attendance_channel_username_stream
  ON stream_attendance(channel_id, username, stream_id);
-- + ещё 6-8 индексов на горячих таблицах
```

**Backfill времени:** ~5-10 секунд на 110k строк. Простой при миграции на проде — терпимо.

---

## §D — Запросы которые надо переписать

**~200-250 запросов** в TENANT-таблицы по всему коду. Распределение:

| Файл | Запросов | Сложность |
|---|---:|---|
| `database.py` | ~80 | Высокая — каждый метод нужно расширить параметром `channel_id` |
| `bot_core.py` | ~45 | Высокая — 3 фоновых loop'а (reward, drop, event_watcher) |
| `routes/duel.py` | ~35 | Средняя — ELO + сезоны + pending |
| `routes/casino.py` | ~20 | Средняя — jackpot, free_spins per-channel |
| `routes/market.py` | ~18 | Средняя |
| `routes/marriage.py` | ~15 | Средняя |
| `routes/viewer.py` | ~15 | Низкая |
| `main.py` | ~12 | Высокая — `market_expiry_loop`, `family_income`, EventSub |
| остальные | ~15 | Низкая |

### Опасные места

1. **`main.py:market_expiry_loop`** — текущий SELECT возвращает все expired лоты без скопа. После рефакторинга должен фильтровать каждый channel_id отдельно или работать на all-channels одним SELECT с `channel_id` в результате.
2. **`main.py:run_family_income`** — тот же случай. SELECT online viewers JOIN marriages — вылет за пределы канала.
3. **`bot_core.py:reward_points_loop`** — массовые UPDATE поинтов. Должен работать per-channel или в одной транзакции с GROUP BY channel_id.
4. **`event_manager.py`** — `donation_total`, `event_pool`, `active_event` сейчас в памяти. Нужно либо `dict[channel_id]` контейнер, либо отдельный EventManager на канал.
5. **`bot.event_manager` global state** — единственный объект. Нужно: либо менеджер per-channel, либо все методы принимают `channel_id`.

---

## §E — JWT / channel_id

Twitch Extension JWT содержит claim `channel_id` (это broadcaster's user_id). Текущий `auth.py` его НЕ извлекает.

**Что менять:**
```python
# auth.py:verify_twitch_jwt
payload = jwt.decode(...)
return {
    "status": "valid",
    "username": payload.get("sub", "") or payload.get("opaque_user_id", ""),
    "user_id": str(payload.get("user_id", "")),
    "channel_id": str(payload.get("channel_id", "")),  # NEW
}
```

```python
# dependencies.py:require_jwt_user
def require_jwt_user(request: Request) -> Optional[Tuple[str, int]]:
    """Возвращает (login, channel_id) или None."""
    jwt_result = verify_twitch_jwt(request)
    if jwt_result.get("status") != "valid":
        return None
    login = sanitize_username(resolve_jwt_login(jwt_result))
    channel_id = int(jwt_result.get("channel_id") or 0)
    if not login or not channel_id:
        return None
    return (login, channel_id)
```

Все 13 эндпоинтов использующих `require_jwt_user` обновляются: распаковка кортежа `username, channel_id = result`. Затем `channel_id` пробрасывается в db-методы.

---

## §F — EventSub

Сейчас регистрируется одна подписка на один `TWITCH_BROADCASTER_ID` из конфига. Для multi-tenant — нужно регистрировать **по подписке на каждого активного стримера**.

**Изменения в `main.py:eventsub_channel_points`:**
- Извлекать `broadcaster_user_id` из event payload — это `channel_id`.
- В `INSERT INTO channel_points_log` добавлять `channel_id`.
- В дедупе по `redemption_id` — `WHERE channel_id=? AND twitch_redemption_id=?`.

**Изменения в `register_eventsub_channel_points`:**
- Перебрать всех зарегистрированных стримеров (новая таблица `channels`), на каждого зарегистрировать свою подписку.
- Использовать общий `EVENTSUB_SECRET` для всех (или отдельный per-channel — обсудимое решение).

---

## §H — Lifecycle каталогов и пешек (session-scoped)

`shop_catalog` и `rimworld_event_catalog` — это **scratch-кэш** активной сессии стримера, не persistence.

**При `POST /api/rimworld/session-start` (мод стартанул новую игру):**
```sql
DELETE FROM shop_catalog          WHERE channel_id = ?;
DELETE FROM rimworld_event_catalog WHERE channel_id = ?;
DELETE FROM rimworld_pawns        WHERE channel_id = ?;
-- pawn-зависимые таблицы (skills, hediffs, traits, genes, equipment, purchase_counters)
-- удаляются каскадом через FK или явным DELETE WHERE pawn_id IN (...).
```

**При `POST /api/rimworld/offline` (мод отключился):** ничего не делаем — пешки/каталог остаются на диске чтобы пережить рестарт мода. Сжигаются только при следующем session-start (новая сейв-игра).

**При смене активного модуля стримера** (admin-UI action): тот же session-start clear но для всех таблиц данного модуля.

**Размер:** на 50 одновременно активных RimWorld-стримеров — ~125 000 строк каталогов. Когда мод офлайн — данные есть, но не растут. На 100 стримеров играют тоже примерно одновременно ~30-40 — не масштабная проблема.

---

## §I — Eager registration + admin-UI lite (M4 расширен)

В отличие от lazy-варианта, **новый стример обязан зарегистрироваться** до того как его зрители смогут пользоваться extension'ом.

**Когда JWT с `channel_id` приходит, а в `channels` нет записи:**
- Бэк возвращает 403 + `{status: "channel_not_registered"}`
- Frontend показывает: «Стример пока не подключил расширение. Попроси его зайти на shedoy23.ru/streamer и активировать»

**Регистрация стримера:** на отдельной странице (не extension):
- `shedoy23.ru/streamer` — кнопка «Sign in with Twitch»
- Twitch OAuth → callback → создание записи в `channels` (Free tier по умолчанию)
- После регистрации — admin-UI lite с базовыми возможностями

**Admin-UI lite в MVP содержит:**
- Текущий тариф (Free / Pro / VIP)
- Кнопка «Connect Channel Points» (OAuth flow для EventSub auto-registration)
- Выбор активного модуля (когда модулей будет несколько)
- Настройка цен/наличия предметов в shop (после Module API внедрения)
- Простая статистика (балансы топ-10 зрителей, число активных дней)

**Полный SaaS-дашборд** (графики, billing, ретеншн-метрики, маркет-аналитика) — отдельный этап M7+.

---

## Этапы M1-M6 — оценка времени (с учётом обсуждённых решений)

| Этап | Описание | Часы |
|---|---|---:|
| **M1** | Schema migration (DDL + backfill + индексы) | 4-6 |
| **M2** | JWT/dependencies (`require_jwt_user` возвращает `channel_id`) | 2-3 |
| **M3** | Query scoping (`database.py`, `bot_core.py`, все routes) | 12-18 |
| **M4** | **Расширен:** `channels` registry + Twitch OAuth для стримера + admin-UI lite + EventSub auto-register | **15-20** |
| **M5** | Per-channel rate limits + tier-based квоты | 1-2 |
| **M6** | Testing (2 канала, проверка изоляции) + deploy | 3-5 |
| | **Итого** | **37-54 ч** |

**Реалистичный график:** 5-7 рабочих сессий по 6-8 часов = 5-7 недель календарного времени с учётом ревью и тестирования.

---

## Что НЕ покрывается этим планом

Для полноценной платформы потребуется ещё:
- **Channel onboarding flow** — UI для регистрации стримера (signup, выбор тарифа, привязка Twitch Extension secret) → отдельный M7+
- **Billing integration** (Boosty/Robokassa) → отдельный M8+
- **Per-channel customization** (свой каталог shop, свои цены, свои rate-limits) → частично в M4
- **Module activation UI** — стример выбирает «играю в RimWorld» / «играю в Minecraft» → отдельный M9+
- **Cross-channel analytics** для админа платформы → M10+

Эти этапы тоже примерно по 10-30 ч каждый. Полный путь до полной SaaS-платформы — 100-150 ч работы (3-4 месяца календарного времени для соло-разработчика).

---

## История

| Дата | Этап | Коммит | Изменения |
|---|---|---|---|
| 2026-05-01 | M0 | — | WAL подтверждён, бэкапы настроены, discovery audit completed. План M1-M6 утверждён. |
| 2026-05-02 | M0+ | `8f05fb1` | После обсуждения: каталоги стали session-scoped (§H), eager registration + admin-UI lite встроены в M4 (§I), `purchase_counters` → pawn-scoped FK CASCADE. Время: 27-41 ч → 37-54 ч. |
| 2026-05-02 | M1 | `c051201` | Schema migration задеплоен на прод. Все TENANT-таблицы получили `channel_id`, 17 пересозданы с PK включая channel_id. `purchase_counters` → `rimworld_purchase_counters` (FK CASCADE). 140 viewers backfill'ены `channel_id=98319857`. Миграция идемпотентна через `migrations_applied`. БД 9.4 → 12.5 MB. |
| 2026-05-04 | M2 | `b7d9c09` | JWT layer. `auth.verify_twitch_jwt` извлекает `channel_id` claim. `dependencies.require_jwt_user` → `(login, channel_id)`. Новый helper `require_jwt_channel`. 20 callsites мигрированы. 5 баговых JWT-проверок в `rimworld.py` исправлены (сравнение dict с 'none' всегда False — auth был де-факто отключён). 11 файлов, +169/−128. |
| 2026-05-04 | M1-fix | `c3a18c4` | 16 ON CONFLICT(username) → ON CONFLICT(channel_id, ...). Helpers `add_points/give_item/touch_viewer/record_attendance/register_stream_session/end_stream_session` приняли opt-in `channel_id` с fallback к `DEFAULT_CHANNEL_ID`. Затронуты viewers, inventory, craft_stats, stream_attendance, stream_streaks, stream_sessions, rimworld_pawns. 10 файлов, +148/−110. |
| 2026-05-04 | M3.0 | `6883170` | Query scoping. `database.py`: 22 метода приняли `channel_id`-параметр + WHERE channel_id=? скоупинг. `bot_core.py`: `reward_points_loop`/`drop_loop` читают channel_id из viewers-row. `main.py`: `family_income_loop` проверяет (channel_id, username) пары; EventSub берёт channel_id из event payload. 3 файла, +281/−181. |
| 2026-05-04 | M3.0.1 | `7f83b71` | ContextVar auto-propagation. `dependencies._current_channel_id: ContextVar` — глобальный контекст request-task'и. `require_jwt_user/_channel` вызывают `.set(channel_id)`. `resolve_channel_id(channel_id=None) -> int` — единая точка fallback'а: явный_параметр → ContextVar → DEFAULT_CHANNEL_ID. 37 inline if-блоков заменены. **Главный выигрыш:** routes/* (50+ callsites без channel_id) автоматически scoped через ContextVar — не требуют изменений. M3.1 фактически отменён. 7 файлов, +100/−114 (NET −14). |
| | M4 | — | **Не начат.** channels registry + Twitch OAuth страница для стримера + admin-UI lite + EventSub auto-register + IRC bot scoping. После M4 убрать `DEFAULT_CHANNEL_ID` fallback. |
| | M5 | — | Не начат. Per-channel rate limits + tier-based квоты. |
| | M6 | — | Не начат. Testing 2 каналов + deploy. |
