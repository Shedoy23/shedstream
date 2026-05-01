# Multi-tenant рефакторинг — план

**Status:** M0 Discovery completed (2026-05-01)
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
| `promocodes` | TENANT в новой модели | Каждый стример сам создаёт промокоды для своих зрителей. Раньше было одно поле для всех — теперь стрсимеры независимы. |
| `rimworld_catalog` | GLOBAL | Это статика мода, не кастомизируется. |
| `shop_catalog` | TENANT в Module API | По §9 спеки `module_shop` публикуется per-channel модулем. Сейчас TODO. |
| `achievements` | GLOBAL для MVP | Кастомные ачивки per-channel — будущая фича. |

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

## Этапы M1-M6 — оценка времени

| Этап | Описание | Часы |
|---|---|---:|
| **M1** | Schema migration (DDL + backfill + индексы) | 4-6 |
| **M2** | JWT/dependencies (`require_jwt_user` возвращает `channel_id`) | 2-3 |
| **M3** | Query scoping (`database.py`, `bot_core.py`, все routes) | 12-18 |
| **M4** | Channel registry (`channels` таблица, регистрация, активация модулей) | 5-7 |
| **M5** | Per-channel rate limits + tier-based квоты | 1-2 |
| **M6** | Testing (2 канала, проверка изоляции) + deploy | 3-5 |
| | **Итого** | **27-41 ч** |

**Реалистичный график:** 4-5 рабочих сессий по 6-8 часов = 4-5 недель календарного времени с учётом ревью и тестирования.

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

| Дата | Этап | Изменения |
|---|---|---|
| 2026-05-01 | M0 | WAL подтверждён, бэкапы настроены, discovery audit completed. План M1-M6 утверждён. |
