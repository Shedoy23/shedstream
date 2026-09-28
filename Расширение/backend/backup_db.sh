#!/bin/bash
# backup_db.sh — ежедневный бэкап БД с ротацией.
#
# Использование (из cron) — ВЫЗЫВАТЬ ЧЕРЕЗ bash, не напрямую:
#   0 5 * * * /bin/bash /root/twitch-extension/backend/backup_db.sh >> /root/twitch-extension/logs/backup.log 2>&1
# (2026-06-11: деплой пересоздавал файл без флага +x → прямой запуск падал с
#  "Permission denied", и daily-бэкап тихо встал на 10 дней. Вызов через bash
#  иммунен к потере +x.)
#
# Работает атомарно через .backup команду SQLite — не корраптится даже если бот пишет.
# Хранит последние 14 ежедневных + 8 еженедельных снимков.

set -euo pipefail

DB_PATH="/root/twitch-extension/backend/viewers.db"
BACKUP_DIR="/root/twitch-extension/backups"
DATE=$(date +%F)            # 2026-05-01
DAY_OF_WEEK=$(date +%u)     # 1=пн ... 7=вс
KEEP_DAILY=14               # хранить ежедневных копий
KEEP_WEEKLY=8               # хранить еженедельных (по воскресеньям)

mkdir -p "$BACKUP_DIR"

if [ ! -f "$DB_PATH" ]; then
    echo "[$(date)] ERROR: БД не найдена: $DB_PATH"
    exit 1
fi

# Атомарный бэкап через sqlite3 .backup — корректно работает на живой БД (использует WAL).
# В отличие от cp, не оставляет частично записанные страницы.
DAILY_PATH="$BACKUP_DIR/viewers.daily.$DATE.db"
sqlite3 "$DB_PATH" ".backup '$DAILY_PATH'" 2>&1

if [ ! -s "$DAILY_PATH" ]; then
    echo "[$(date)] ERROR: бэкап пустой"
    exit 1
fi

# Сжимаем (zstd экономит ~70% при ~10x скорости gzip; если zstd нет — используем gzip)
if command -v zstd >/dev/null 2>&1; then
    zstd -q -19 --rm "$DAILY_PATH"
    DAILY_PATH="${DAILY_PATH}.zst"
elif command -v gzip >/dev/null 2>&1; then
    gzip -9 "$DAILY_PATH"
    DAILY_PATH="${DAILY_PATH}.gz"
fi

SIZE=$(du -h "$DAILY_PATH" | awk '{print $1}')
echo "[$(date)] DAILY backup OK: $DAILY_PATH ($SIZE)"

# По воскресеньям делаем weekly-копию (просто хардлинк в weekly-папку)
if [ "$DAY_OF_WEEK" = "7" ]; then
    WEEKLY_PATH="$BACKUP_DIR/viewers.weekly.$DATE.${DAILY_PATH##*.}"
    cp "$DAILY_PATH" "$WEEKLY_PATH"
    echo "[$(date)] WEEKLY backup OK: $WEEKLY_PATH"
fi

# Ротация: удаляем старые
find "$BACKUP_DIR" -name "viewers.daily.*" -mtime "+$KEEP_DAILY" -delete
find "$BACKUP_DIR" -name "viewers.weekly.*" -mtime "+$((KEEP_WEEKLY * 7))" -delete

# Отчёт
DAILY_COUNT=$(find "$BACKUP_DIR" -name "viewers.daily.*" | wc -l)
WEEKLY_COUNT=$(find "$BACKUP_DIR" -name "viewers.weekly.*" | wc -l)
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" | awk '{print $1}')
echo "[$(date)] Состояние бэкапов: daily=$DAILY_COUNT, weekly=$WEEKLY_COUNT, total=$TOTAL_SIZE"
