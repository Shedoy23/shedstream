# Public-Gate Plan — путь от приватного ревью к публичному релизу

**Дата:** 2026-06-29. **Основание:** сводка 6 параллельных разведок (submission-доки,
ROADMAP, лексикон UI, монетизация/данные, LGPL, публичные поверхности бэка).

## Вердикт

| Уровень | Статус | Блокеры |
|---|---|---|
| Приватное ревью (Submit for Review) | 🟢 ~95% — подавать после Фазы 1 | «Задонатить»-лейбл, config-toggle live-проверка |
| Публичный доступ (Released, any-streamer) | 🟡 нужен public-gate батч | 3 auth-дыры чтения, тонкий фронт, CSP, RimWorld-кластер |

Подача ревью и «Released» — разные ворота: ревью приватное, «Released» жмёт владелец
отдельно. Public-gate можно закрывать, пока Twitch проверяет.

## Фаза 0 — свежие правила (30 мин)
`/twitch-compliance`: перечитать CP Acceptable Use + Extension Guidelines (+ToS если
монетизация) на дату фикса. Аудит 2026-06-11 мог устареть в деталях.

## Фаза 1 — полиш перед подачей (~2-3 ч)
1. `viewer-shedcolony.js:390` — «📦 Задонатить (стак)» → «📦 Снабдить колонию».
   Внутренний ключ `colony.donate` → `colony.supply` координированно:
   `modules/shedcolony/manifest.yaml` + `routes/shedcolony.py` + C#-мод (ATM10-сервер
   `/opt/atm10/mods/shedcolony-0.1.0.jar` — пересборка из D:\sheddev + redeploy).
2. Казино-tombstone-комменты в viewer.js/overlay.html — вычистить;
   `tournament.bet` → `tournament.predict` (фронт+бэк), чтобы термин не светился в XHR.
3. **Владелец:** live-проверка config.html в реальном Twitch config view (частый
   реджект), скриншот 1024×768, ZIP → Hosted Test → Submit
   (гайд: docs/SUBMIT_AND_REVIEW.md).

## Фаза 2 — окно ревью: freeze контракта v1.0
Бэкенд общий у поданного фронта и dev-веток → на время ревью не ломать/не
переименовывать эндпоинты, которые зовёт v1.0 фронт. Добавить смоук «v1.0 контракт»
в deploy-гейт.

## Фаза 3 — public-gate (~1-2 сессии, ДО «Released»)
1. **Auth-дыры чтения** (см. surfaces-разведку):
   - `rimworld.py:571` GET `/api/rimworld/my-pawn/{username}` — вообще без auth,
     полный профиль пешки. JWT + channel-scope (или killswitch модуля, п.2).
   - `viewer.py:295` `/api/user/level/{username}` и `viewer.py:371`
     `/api/viewer/online-list` — fallback на resolve_channel_id_or_default() без JWT
     → убрать fallback (401 без JWT).
   - `module_api.py:35/55` `/v1/modules{,/info}` — скрыть или auth (capability-разведка).
   - `misc.py:189` `/api/user/resolve-twitch-id` — auth/удалить (enumeration-оракул).
2. **RimWorld-кластер** (5 findings, task_f2662300): починить ИЛИ настоящий
   kill-switch (эндпоинты 404 при выключенном модуле; RIMWORLD_REQUIRE_TOKEN=1).
3. **Тонкий фронт** (ROADMAP §5): BNR_FOCUS_TIER_COSTS, BNR_ATTRIBUTE_COST,
   RETINUE_TIER_DINARS, RECRUIT_PRICE_BASIC, EVENT_COOLDOWN_MS, trait/gene-цены →
   отдавать с бэка (/my-hero, /config). CDN-фронт замёрзнет — цены живут на бэке.
4. **CSP/CORS** (`main.py:264-295`): добавить script-src/connect-src/default-src;
   пересмотреть `null`-origin + allow_credentials (OBS-кейс — сузить).
5. **Гигиена до 2-го стримера:** DEFAULT_CHANNEL_ID fallback (config.py:695),
   мёртвые bits-колонки pet_purchases + PETS_BITS_REQUIRED dead-path,
   boosty_tier в /api/viewer/role — пометить cosmetic-only/убрать.
6. **Масштаб:** замерить poll-амплификацию (~12-16 req/8с на зрителя) на реальном
   стриме; прикинуть 50 каналов (SQLite один).

## Фаза 4 — гейт с доказательствами
Лексикон-линт (расширить на комменты), tenant-линт, критические тесты (107),
/security-review диффа public-gate, чек-лист сюда. Только после зелёного — «Released».

## Не забыть
- BLT не упоминать в листинге/промо (риск-решение 2026-06-12).
- Во время ревью прод не рестартить в момент теста ревьюера (мониторить UptimeRobot).
- Данные: privacy/terms живые; удаление данных — вручную по email (осознанный gap).
