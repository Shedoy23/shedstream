# Public-Gate Plan — путь от приватного ревью к публичному релизу

**Дата:** 2026-06-29. **Основание:** сводка 6 параллельных разведок (submission-доки,
ROADMAP, лексикон UI, монетизация/данные, LGPL, публичные поверхности бэка).

## Вердикт

| Уровень | Статус | Блокеры |
|---|---|---|
| Приватное ревью (Submit for Review) | 🟢 ~95% — подавать после Фазы 1 | «Задонатить»-лейбл, config-toggle live-проверка |
| Публичный доступ (Released, any-streamer) | 🟢 public-gate закрыт (2026-07-02) | остался только замер poll-нагрузки на живом стриме + in-game проверка UI |

Подача ревью и «Released» — разные ворота: ревью приватное, «Released» жмёт владелец
отдельно. Public-gate можно закрывать, пока Twitch проверяет.

## Фаза 0 — свежие правила (30 мин)
`/twitch-compliance`: перечитать CP Acceptable Use + Extension Guidelines (+ToS если
монетизация) на дату фикса. Аудит 2026-06-11 мог устареть в деталях.

## Фаза 1 — полиш перед подачей (~2-3 ч)
1. ✅ 2026-07-02 «Задонатить» → «Снабдить колонию»; `colony.donate` → `colony.supply`
   по всей цепочке (manifest + routes + frontend + Java-мод, jar пересобран и
   выложен на ATM10 — применится при следующем рестарте сервера; бэк уже на проде,
   окно рассинхрона безопасно: refund-on-failure + 0 колоний).
2. ✅ 2026-07-02 tombstone-комменты вычищены (viewer.js/cases.js/overlay/обе оболочки);
   `tournament.bet` → `tournament.predict` end-to-end (+ manifest bannerlord,
   my_bet → my_prediction, min/max_bet удалены); REVIEW_SUBMISSION.md обновлён.
   Прод проверен: оба манифеста и фронт отдают новые имена. Тесты 107/107 + 13/13.
3. **Владелец (осталось):** live-проверка config.html в реальном Twitch config view
   (частый реджект), скриншот 1024×768, ZIP → Hosted Test → Submit
   (гайд: docs/SUBMIT_AND_REVIEW.md).

## Фаза 2 — окно ревью: freeze контракта v1.0
Бэкенд общий у поданного фронта и dev-веток → на время ревью не ломать/не
переименовывать эндпоинты, которые зовёт v1.0 фронт. Добавить смоук «v1.0 контракт»
в deploy-гейт.

## Фаза 3 — public-gate ✅ СДЕЛАНО 2026-07-02 (задеплоено, прод-проверено)
Три волны, каждая — отдельный коммит; деплой-гейт 107/107; прод отвечает верно.
1. ✅ **Auth-дыры чтения (wave 1, commit 05737fb):**
   - `my-pawn/{username}` → require JWT + own-login-only → без JWT `{exists:false,
     auth_required:true}` (вкладка ревьюера рисует «создать пешку», не ломается).
   - `user/level` / `online-list` → без JWT нейтральные дефолты / пустой список
     (fallback на default-канал убран). Фронт шлёт X-Twitch-JWT.
   - `add-command` (был БЕЗ auth, инъекция команд) → под rimworld_mod_auth.
   - `resolve-twitch-id` → admin-basic (0 вызовов, enumeration-оракул).
   - `/v1/modules` + `/info` → 404 без `EXPOSE_MODULE_DEBUG=1` (0 вызовов).
2. ✅ **RimWorld:** my-pawn + add-command закрыты (см. wave 1). Остаток кластера
   (SOFT mod-ingest, colonists-leak) — под `task_f2662300`, чинить при реактивации
   RimWorld (модуль сейчас dormant; RIMWORLD_REQUIRE_TOKEN держим 0 до апдейта мода).
3. ✅ **Тонкий фронт (wave 3, commit 4080cc5):** новый GET `/api/bannerlord/config`
   отдаёт все ~10 констант; фронт гидрирует их на активации модуля, хардкоды —
   fallback. CDN-фронт можно морозить: ребаланс на бэке подхватится без ре-ревью.
4. ✅ **CSP/CORS (wave 2, commit 02b6048):** allow_headers сужен со `*`;
   Permissions-Policy (camera/mic/geo off). `null`-origin + credentials оставлены
   (OBS; SameSite=Lax уже защищает). Полный script-src CSP = отдельная задача
   (вынос inline-скриптов дашборда).
5. ✅ **Гигиена:** boosty_tier помечен display-only; pets bits — комментарий (без
   миграции). DEFAULT_CHANNEL_ID fallback убран из viewer-data reads (п.1).
6. ⏳ **Масштаб (не сделано — нужен живой стрим):** замерить poll-амплификацию
   (~12-16 req/8с на зрителя), прикинуть 50 каналов (SQLite один). Пост-стрим.

## Фаза 4 — гейт с доказательствами
Лексикон-линт (расширить на комменты), tenant-линт, критические тесты (107),
/security-review диффа public-gate, чек-лист сюда. Только после зелёного — «Released».

## Не забыть
- BLT не упоминать в листинге/промо (риск-решение 2026-06-12).
- Во время ревью прод не рестартить в момент теста ревьюера (мониторить UptimeRobot).
- Данные: privacy/terms живые; удаление данных — вручную по email (осознанный gap).
