# RimLink — Context Handoff

**Для:** быстрый ввод нового Claude-чата в контекст проекта.
**Last updated:** 2026-05-14

## TL;DR

**Twitch Extension** для viewer engagement. Основной канал: `twitch.tv/shedoy23`.
Backend на VPS Timeweb (`31.130.132.224`), frontend хостится на `shedoy23.ru`.
Single-stream сейчас, multi-tenant архитектура готова. Цель — пройти Twitch
review и стать **multi-game platform** (RimWorld → Bannerlord → Minecraft).

## Stack

- **Backend:** Python FastAPI + aiosqlite (DBPool) + twitchio bot
- **Frontend:** Vanilla JS (`extension.html`, `mobile.html`, `overlay.html`, `config.html`)
- **Game mod:** RimWorld C# (Harmony patches)
- **БД:** SQLite (`viewers.db`, WAL), 13 миграций (M1-M13)
- **Auth:** Twitch Extension JWT (HS256, TWITCH_EXTENSION_SECRET)
- **Hosting:** supervisor → uvicorn на порту 8000, nginx reverse proxy

## Текущий статус (Phase 8.H, commit 134a585)

### ✅ Закрыто
- Compliance rework Phase 1-7 — вырезаны casino/craft/market/donate/transfer/
  family-financial/roulette/mystery-boxes/item-bonus
- Replacements: кейсы (4 tier fixed reward), guilds + skills, voting events,
  matchmaking (TicTacToe + Dice), pets MVP (cross-channel cosmetics)
- Phase 8.A-H polish: lexicon scrub, hatch animation, UI cleanup,
  donate removal, mobile = extension copy, admin auth fix, TG notify,
  preview-mode для теста без стрима
- Production deployed, БД wipe + fresh state (Phase 8.C)
- 1073/1073 isolation tests passing
- Telegram-нотификация при go-live (канал @ttvshedoy23)

### 🔴 Блокер для Twitch submission
1. Описание в Twitch Extension Store → переписать на «multi-game platform»
2. Frontend zip → загрузить в Twitch Hosted Test → активировать Released
3. Submission notes — копипаст из `docs/REVIEW_SUBMISSION.md`

### 🟡 Soft requirements
- Promo-код для reviewer'а (admin endpoint `/api/admin/case/grant` готов)
- Видео-демо 3-5 мин (optional)
- Тест-канал live при ревью

### 🟢 Intentional DEFERRED (после launch)
- `[BITS-SIG]` real Twitch Bits signature verify (сейчас mock-mode)
- `[BROADCASTER-JWT]` streamer toggle через role='broadcaster' (сейчас admin)
- Generic UI renderer (overkill пока, см. предыдущие обсуждения)

### ⚪ Future (отложено осознанно)
- Bannerlord module (3-5 недель, backend + C# mod)
- Battle pass / sезоны
- Турниры между гильдиями
- Community marketplace для модулей

## Ключевые файлы (репо)

| Где | Что |
|---|---|
| `Расширение/docs/PROJECT_PLAYBOOK.md` | Roadmap, метрики, B2B-вижн |
| `Расширение/docs/ARCHITECTURE.md` | Multi-tenant invariants, layers, §3.1 cross-channel exception |
| `Расширение/docs/COMPLIANCE_REWORK_PLAN.md` | 6 фаз compliance + verdict-таблица 16 механик |
| `Расширение/docs/REVIEW_SUBMISSION.md` | Submission notes для Twitch reviewer'а |
| `Расширение/docs/TELEGRAM_SETUP.md` | TG-нотификации + /etc/hosts fix |
| `Расширение/docs/MODULE_API.md` | Game Bridge SDK для новых игр |
| `Расширение/backend/main.py` | FastAPI app + startup + migrations |
| `Расширение/backend/bot_core.py` | IRC bot + reward loops + matchmaking |
| `Расширение/backend/database.py` | Всё SQL + helpers |
| `Расширение/backend/routes/*.py` | По endpoint group (pets, cases, guilds, voting, ...) |
| `Расширение/backend/migrations/m1-m13_*.py` | Schema migrations |
| `Расширение/backend/notifications.py` | Telegram sendMessage helper |
| `Расширение/frontend/extension.html` | Главный UI (320 строк) |
| `Расширение/frontend/mobile.html` | КОПИЯ extension.html (sync через deploy) |

## Server info

- **Host:** `root@31.130.132.224` (Timeweb VPS)
- **Path:** `/root/twitch-extension/{backend,frontend,admin,docs,backups,logs}`
- **Supervisor:** `/etc/supervisor/conf.d/twitchbot.conf` → uvicorn на 8000
- **Nginx:** `/etc/nginx/sites-enabled/` → reverse proxy `shedoy23.ru` → :8000
- **Logs:** `/var/log/twitchbot.{out,err}.log` (logrotate настроен: daily/10M/7days)
- **Backups:** `/root/twitch-extension/backups/` (daily через `backup_db.sh` cron)
- **DB:** `/root/twitch-extension/backend/viewers.db`
- **Admin:** `https://shedoy23.ru/admin` (HTTP Basic, creds в .env)

## Deploy

Нет CI. Manual через tar-pipe SSH:
```bash
cd Расширение
tar -cz backend/X frontend/Y | ssh root@31.130.132.224 \
  'cd /root/twitch-extension && tar -xz && supervisorctl restart twitchbot'
```

Detail: `git push origin HEAD:main` → потом manual tar-pipe.

## Live testing (без стрима)

Twitch не показывает extension panel когда канал offline. Решение —
**standalone preview**:
```bash
curl -u shedoy23:PASS "https://shedoy23.ru/api/admin/dev/jwt?username=shedoy23&minutes=60"
```
→ открыть `preview_url` в браузере. Работает с любого устройства.

## Что обсуждали недавно

- **Mobile UI:** mobile.html был legacy (2247 строк без новых фич), сделали
  копией extension.html (parity)
- **Donate:** убрали полностью (§5.2/§5.4 compliance violation), dead code
  + UI элементы вырезаны
- **Generic UI renderer:** обсудили, решили НЕ делать сейчас (premature
  optimization для 1-2 модулей)
- **Whitelist auto-add:** Twitch не даёт API для управления test-whitelist'ом.
  Возможна полумера: queue в БД + admin endpoint выдаёт CSV для копи-paste.
  Юзер ещё не решил делать или нет.
- **Phase 8.H preview-mode:** работает, login cache pre-populate hotfix

## Open вопросы

1. Запускать **whitelist queue** (auto-collect ников из channel point
   redemption "ПОЛУЧИТЬ ДОСТУП")?
2. Когда **Twitch submission** — после каких ещё фич?
3. Включать **PETS_BITS_REQUIRED=true** на проде (сейчас mock) — после
   регистрации Bits products в Twitch dashboard
4. Как поступить с EventSub `stream.online` — добавлять для instant
   нотификации (сейчас 0-120s latency через polling)?

## Команды для быстрой проверки

```bash
# Status сервера
ssh root@31.130.132.224 'supervisorctl status twitchbot && df -h /root | head -2'

# Свежие логи
ssh root@31.130.132.224 'tail -30 /var/log/twitchbot.err.log'

# Live кейсы у юзера
ssh root@31.130.132.224 'sqlite3 /root/twitch-extension/backend/viewers.db \
  "SELECT id, tier, opened_at FROM cases WHERE username=\"shedoy23\""'

# Текущий баланс
curl -u shedoy23:PASS "https://shedoy23.ru/api/admin/user/shedoy23"

# Preview URL (1 час)
curl -u shedoy23:PASS "https://shedoy23.ru/api/admin/dev/jwt?username=shedoy23"
```

## Repo

- **GitHub:** `Shedoy23/shedstream` (private monorepo)
- **Default branch:** `main`
- **Текущий HEAD:** `134a585` (Phase 8.H preview-mode hotfix)

---

**Точка входа для нового чата:** скинуть этот файл + сказать
*«Читай CONTEXT.md, продолжаем работу. Сейчас хочу обсудить X»*.
