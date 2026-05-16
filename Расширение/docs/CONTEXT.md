# RimLink — Main Context (chat handoff)

**Назначение:** для чата по **общей** части расширения. Если работа над
конкретным модулем — см. `CONTEXT_RIMWORLD.md` или `CONTEXT_BANNERLORD.md`.

**Last updated:** 2026-05-16 (Phase A: EventSub realtime landed)

## TL;DR

Twitch Extension для viewer engagement. Multi-tenant FastAPI backend +
SQLite + twitchio bot + vanilla JS frontend. Запускается у одного
streamer'а сейчас (`twitch.tv/shedoy23`) — продакшн на Timeweb VPS
`31.130.132.224`, домен `shedoy23.ru`.

Архитектурно — **platform с pluggable game modules**:
- **Core (game-agnostic):** balance, kasy, gilds, voting, matchmaking
  (TicTacToe / Dice), pets (cross-channel cosmetic), Twitch chat hooks,
  channel-points integration, TG notifications, dev login, OAuth
- **Game modules:** RimWorld (legacy + Phase 7 refactor) и Bannerlord
  (Sprint 4.3 — classes + powers MVP)

## Текущий статус

### ✅ Закрыто
- **Phase 1-7 compliance rework** — casino/craft/market/donate/transfer
  вырезаны, replaced на cases/guilds/voting/matchmaking/pets
- **Phase 8 polish** — lexicon, hatch animation, mobile parity, donate
  removal, TG notify, admin auth fix, preview-mode
- **Dev login flow** (`/dev`) — Twitch OAuth + persistent test access
- **Phase A: EventSub realtime (2026-05-16, commit `506f9d7`)** — `backend/eventsub.py`
  generic dispatcher с HMAC verify, 10-мин replay window, dedupe table (M17),
  multi-tenant channel gate, handler-exception caught (нет 5xx → нет Twitch
  retry-loop). Регистрируются 3 подписки на канал: channel_points (existing)
  + stream.online + stream.offline. TG-нотификация теперь приходит за 1-3 сек
  (vs 0-120s polling). `_is_stream_live` polling TTL: 120s→300s (fallback).
  **EVENTSUB_SECRET ротирован** на 32-byte url-safe.
- **Compliance mini-audit (2026-05-16, commit `cda5105`)** — research подтвердил
  что CP→in-extension currency Twitch разрешает с условиями. Применено:
  disclosure footer на extension/mobile («алмазы не имеют денежной ценности»),
  CSS class `quick-bet`→`quick-vote`, winner modal «Выигрыш»→«Награда»,
  CP reward titles в config.py «N очков → алмазы»→«Награда: N алмазов»
  (синхронизировано с Twitch Creator Dashboard).
- **1088/1088 isolation tests + 34/34 EventSub security tests** passing
- **Production deployed** — supervisor RUNNING, БД чистая, logrotate

### 🔴 Блокер для Twitch submission
1. Description в Twitch Extension Store → переписать на «multi-game platform»
2. Frontend zip → upload в Twitch Hosted Test → Released
3. Submission notes — `docs/REVIEW_SUBMISSION.md`

### 🟢 Intentional DEFERRED (после launch)
- [BITS-SIG] real Twitch Bits transaction JWT signature verify
- [BROADCASTER-JWT] streamer toggle через role='broadcaster'
- Generic UI renderer (overkill пока для 2 модулей)

## Stack

- **Backend:** Python FastAPI + aiosqlite (DBPool) + twitchio bot
- **Frontend:** Vanilla JS (`extension.html`, `mobile.html`,
  `overlay.html`, `config.html`)
- **Game mod:** RimWorld C# (Harmony patches), Bannerlord C# (net472)
- **БД:** SQLite + WAL, 17 migrations (M1-M17)
- **Auth:** Twitch Extension JWT (HS256, `TWITCH_EXTENSION_SECRET`)
- **Hosting:** supervisor → uvicorn :8000, nginx reverse proxy
- **TG notifier:** stream-online → Telegram channel (см. `TELEGRAM_SETUP.md`)
- **Realtime:** EventSub webhook → backend/eventsub.py (stream.online/offline,
  channel_points). Подробнее в Phase A entry выше.

## Server / deploy

- **Host:** `root@31.130.132.224` (Timeweb VPS, SSH key auth)
- **Path:** `/root/twitch-extension/{backend,frontend,admin,docs,backups,logs}`
- **Supervisor:** `/etc/supervisor/conf.d/twitchbot.conf`
- **Logs:** `/var/log/twitchbot.{out,err}.log` (logrotate daily/10M/7d)
- **DB:** `/root/twitch-extension/backend/viewers.db`
- **Admin panel:** `https://shedoy23.ru/admin` (HTTP Basic, creds в .env)
- **Dev login:** `https://shedoy23.ru/dev` (Twitch OAuth, persistent cookie)

### Deploy
Нет CI. Manual tar-pipe SSH:
```bash
cd Расширение
tar -cz backend/X frontend/Y | ssh root@31.130.132.224 \
  'cd /root/twitch-extension && tar -xz && supervisorctl restart twitchbot'
```

## Ключевые файлы

| Где | Что |
|---|---|
| `Расширение/docs/PROJECT_PLAYBOOK.md` | Roadmap, метрики, B2B |
| `Расширение/docs/ARCHITECTURE.md` | Multi-tenant, layers, §3.1 cross-channel |
| `Расширение/docs/COMPLIANCE_REWORK_PLAN.md` | 6 фаз compliance + verdict-таблица |
| `Расширение/docs/REVIEW_SUBMISSION.md` | Submission notes для Twitch reviewer'а |
| `Расширение/docs/TELEGRAM_SETUP.md` | TG-нотификации |
| `Расширение/docs/MODULE_API.md` | Game Bridge SDK |
| `Расширение/backend/main.py` | FastAPI app + startup + migrations |
| `Расширение/backend/bot_core.py` | IRC bot + reward loops + matchmaking |
| `Расширение/backend/database.py` | Всё SQL + helpers |
| `Расширение/backend/eventsub.py` | EventSub generic dispatcher (Phase A) |
| `Расширение/backend/routes/` | Routes по features (pets/cases/guilds/voting/...) |
| `Расширение/backend/migrations/m1-m17_*.py` | Schema migrations |
| `Расширение/backend/routes/dev_login.py` | /dev OAuth flow |
| `Расширение/backend/notifications.py` | TG sendMessage helper |
| `Расширение/backend/modules/{rimworld,bannerlord}/` | Module adapters + manifests |
| `Расширение/frontend/extension.html` | Главный UI |
| `Расширение/frontend/mobile.html` | КОПИЯ extension.html |

## Тестирование

### Live test без стрима
1. https://shedoy23.ru/dev → login через Twitch
2. После OAuth → click «Open extension preview»
3. Открывается extension.html с твоим JWT — все фичи работают

Альтернатива: `curl -u admin:pass /api/admin/dev/jwt?username=X&minutes=60`
→ preview_url для конкретного юзера.

### Bypass для отсутствия стрима
Когда нужно тестить action queue без go-live:
```bash
ssh root@31.130.132.224 'sed -i "/TESTING_BYPASS_STREAM_LIVE/d" .env;
                        echo "TESTING_BYPASS_STREAM_LIVE=true" >> .env;
                        supervisorctl restart twitchbot'
```
Не забыть выключить после теста.

## Quick verification

```bash
# Server status
ssh root@31.130.132.224 'supervisorctl status twitchbot && df -h /root | head -2'

# Свежие логи
ssh root@31.130.132.224 'tail -30 /var/log/twitchbot.err.log'

# DB stats
ssh root@31.130.132.224 'sqlite3 /root/twitch-extension/backend/viewers.db \
  "SELECT name FROM migrations_applied ORDER BY applied_at DESC LIMIT 5"'

# Preview URL
curl -u shedoy23:33133313 "https://shedoy23.ru/api/admin/dev/jwt?username=shedoy23"
```

## Open вопросы / next steps

1. Twitch submission — когда финальный заход?
2. Bannerlord Sprint 4.4+ (damage hooks) — отдельный чат рекомендуется (см.
   CONTEXT_BANNERLORD.md)
3. RimWorld rework под new Module API — отдельный чат (см. CONTEXT_RIMWORLD.md)
4. Whitelist auto-add из channel point redemption (обсуждалось, не решено)

## Repo

- **GitHub:** `Shedoy23/shedstream` (private monorepo)
- **Branch:** `main`
- **HEAD:** см. `git log --oneline -1`

---

**Использование для нового чата:** скинуть этот файл + сказать
*«Читай CONTEXT.md, продолжаем работу над main extension»*.
