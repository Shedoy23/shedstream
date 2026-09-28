# RESTORE PLAYBOOK — восстановление БД из бэкапа (на случай паники)

> **Когда это нужно:** прод-БД (`viewers.db`) повреждена, потеряна, или прод не
> стартует из-за БД. Цель — поднять бэкенд на последнем валидном бэкапе с
> минимальной потерей данных.
>
> **Проверено дриллом 2026-06-13 (ROADMAP 2.2):** offsite-копия `viewers.daily.*.db.zst`
> распаковывается, проходит `integrity_check`, поднимает ТЕКУЩИЙ бэкенд (миграции
> применяются на реальных данных), данные целы (1 канал / 42 зрителя / 2.46M💎).
> Это не теория — путь рабочий.

## Где лежат бэкапы

| Где | Что | Назначение |
|---|---|---|
| **VDS** `/root/twitch-extension/backups/` | `viewers.daily.*.db.zst` (14 шт) + `viewers.weekly.*` (8 шт) | основной, быстрый restore если VDS жив. Делается cron'ом (`backup_db.sh`) + in-process (`backup_loop.py`) |
| **ПК (offsite)** `%USERPROFILE%\shedstream-backups\` | копии `viewers.daily.*.db.zst` (14 шт) | disaster-recovery если VDS целиком потерян. Тянется `pull-backup.ps1` (задача `shedstream-db-backup-pull`, daily 13:00) |

Формат имени: `viewers.daily.ГГГГ-ММ-ДД.db.zst`. Сжатие — zstd.

⚠️ **Потеря данных:** бэкапы ежедневные → теряешь до ~1 суток. Offsite-pull может
отставать ещё на день (см. «Известная проблема» внизу) — проверяй дату файла.

---

## Сценарий A — прод-БД битая, но VDS жив (быстрый путь)

```bash
ssh root@31.130.132.224
cd /root/twitch-extension/backend
# 1. Останови бот (держит файл БД)
supervisorctl stop twitchbot
# 2. Отложи битую БД (НЕ удаляй — вдруг частично цела)
mv viewers.db viewers.db.broken-$(date +%F)
# 3. Возьми СВЕЖИЙ бэкап (по дате имени), распакуй
ls -lt ../backups/viewers.daily.*.db.zst | head -3      # выбери верхний
zstd -d -f ../backups/viewers.daily.ГГГГ-ММ-ДД.db.zst -o viewers.db
# 4. Проверь целостность ДО запуска
sqlite3 viewers.db 'PRAGMA integrity_check;'            # должно быть: ok
# 5. Подними бот (миграции прогонятся на старте)
supervisorctl start twitchbot
sleep 7; supervisorctl status twitchbot
# 6. Проверь данные + что бек отдаёт
sqlite3 viewers.db "SELECT count(*) FROM viewers; SELECT COALESCE(sum(points),0) FROM viewers;"
curl -s -o /dev/null -w 'docs=%{http_code}\n' http://127.0.0.1:8000/docs   # 200
```

---

## Сценарий B — VDS потерян целиком (restore из offsite на новый сервер)

1. Подними новый VDS, разверни код проекта (`scripts/deploy.ps1` на новый хост) +
   `.env` (секреты — из своего хранилища, НЕ из бэкапа; в бэкапе только БД).
2. Залей offsite-копию с ПК на новый сервер:
   ```powershell
   scp "$env:USERPROFILE\shedstream-backups\viewers.daily.ГГГГ-ММ-ДД.db.zst" root@НОВЫЙ_VDS:/root/
   ```
3. На сервере — как в сценарии A, шаги 3–6 (распаковать → integrity → положить как
   `backend/viewers.db` → старт → проверка).

---

## Безопасная репетиция (не трогая прод) — через staging

Так дрилл и делался. Повторять можно когда угодно:
```bash
# залить нужную копию на VDS, распаковать в staging БД
scp <копия>.zst root@31.130.132.224:/root/
ssh root@31.130.132.224
zstd -d -f /root/<копия>.zst -o /root/twitch-extension-staging/backend/viewers.db
```
```powershell
pwsh scripts/deploy.ps1 -Staging      # поднимет staging (:8001) на этой БД, health-check
# проверить: ssh ... 'sqlite3 /root/twitch-extension-staging/backend/viewers.db "SELECT count(*) FROM viewers;"'
ssh root@31.130.132.224 'supervisorctl stop twitchbot-staging'   # выключить после
```
Staging изолирован (свой порт + `DISABLE_LIVE_INTEGRATIONS` → не трогает живой канал).

---

## Известная проблема — offsite-pull отстаёт

Задача `shedstream-db-backup-pull` (ПК, daily 13:00) иногда завершается с
`LastResult 0xC000013A` (процесс принудительно убит — ПК спал/выключен посреди scp),
и день не доезжает в offsite. **Скрипт сам рабочий** (ручной прогон тянет нормально).
Костыль на сейчас: иногда прогоняй вручную —
`pwsh %USERPROFILE%\shedstream-backups\pull-backup.ps1` — и сверяй дату последнего
`.zst`. Хардинг задачи (wake-таймер / fail-fast scp с ConnectTimeout) — в backlog (1.1-follow-up).
