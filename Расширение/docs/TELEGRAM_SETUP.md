# Telegram Notifications Setup

Бот шлёт «🔴 Стрим начался!» в TG-канал при go-live. Triggered из
`bot_core._is_stream_live` polling (transition False→True), no-op
если env не сконфигурирован.

## 1. Создать бота

1. Telegram → найти `@BotFather` → `/newbot`
2. Дать имя + username (e.g. `@your_notify_bot`)
3. Сохранить **bot token** вида `1234567890:ABCdef...`

## 2. Узнать chat_id канала

**Public channel** (есть `@handle`):
- `chat_id = @your_channel_handle` (со @)

**Private channel:**
- Добавить бота как admin (нужен post-messages permission)
- Переслать любое сообщение из канала в `@userinfobot` → получишь ID
- `chat_id = -1001234567890` (с минусом, без @)

**Личка (для теста):**
- Написать боту `/start`
- chat_id = твой Telegram user_id

## 3. .env на проде

```
TELEGRAM_BOT_TOKEN=1234567890:ABCdef...
TELEGRAM_CHAT_ID=@your_channel
TELEGRAM_NOTIFICATIONS_ENABLED=true
```

После — `supervisorctl restart twitchbot`.

## 4. КРИТИЧНО для Timeweb VPS — /etc/hosts override

**Проблема:** на Timeweb VPS (Москва) DNS отдаёт `149.154.166.110`
для `api.telegram.org` — этот IP заблокирован РКН. Соседний DC
`149.154.167.220` работает.

**Fix:**
```bash
echo "149.154.167.220 api.telegram.org" >> /etc/hosts
```

Persistent через reboot. Может стереться при system update (Ansible-managed
блок в hosts). Если перестал работать — проверь:
```bash
curl --max-time 5 https://api.telegram.org -o /dev/null -w "%{http_code}\n"
```

200 = ОК. 000/timeout = IP опять blocked, замени на резерв:
- `149.154.167.51` (DC2)
- `149.154.175.50` (DC1)
- `149.154.175.100` (DC3)
- `149.154.167.91` (DC4)

## 5. Тест без go-live

```bash
ssh root@SERVER
cd /root/twitch-extension/backend
/root/twitch-extension/venv/bin/python -c "
import asyncio, os
for line in open('.env'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1); os.environ[k] = v
import notifications
notifications._last_notified.clear()  # сброс cooldown
asyncio.run(notifications.notify_stream_online(
    channel_id=98319857, login='shedoy23',
    title='Тест', game='RimWorld',
))
"
```

## 6. Anti-spam

- 30 мин cooldown per channel_id (`TG_RENOTIFY_COOLDOWN` в `notifications.py`)
- Cold start: если backend рестартанул когда стрим уже шёл — `cached=None`,
  trigger не fire'ит (фича — не дублируем «начался» при каждом deploy)

## 7. Latency

- Twitch event → Helix reflects: ~5-30 сек
- Helix → наш poll: 0-120 сек
- Notify → TG delivery: <1 сек
- **Total: ~5-150 сек** после реального старта стрима

## 8. Failure modes

| Что | Симптом | Fix |
|---|---|---|
| Token неверный | `getMe` returns `{"ok":false}` | Re-generate в @BotFather |
| chat_id неверный | `sendMessage` returns `chat not found` | Проверь формат (см. §2) |
| IP заблокирован | `curl --max-time 5 api.telegram.org` → timeout | Update `/etc/hosts` (см. §4) |
| Бот не в канале | `chat not found` для private | Добавь бота как admin |
| No post-permission | `403 Forbidden: not enough rights` | Дай боту permission «Post Messages» |

## 9. Disable

Установить `TELEGRAM_NOTIFICATIONS_ENABLED=false` в .env + restart.
Никаких side effects.
