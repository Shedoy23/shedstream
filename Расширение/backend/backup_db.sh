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

# Общая проверенная реализация: SQLite backup + quick_check, zstd 3 (gzip 1
# fallback), проверка распаковки/SHA256, атомарная публикация. При ошибке старая
# готовая копия остаётся; set -e не даст перейти к ротации.
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PYTHON="$SCRIPT_DIR/../venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON=python3
fi
DAILY_PATH=$("$PYTHON" "$SCRIPT_DIR/backup_storage.py" \
    --source "$DB_PATH" --destination "$BACKUP_DIR/viewers.daily.$DATE.db")

SIZE=$(du -h "$DAILY_PATH" | awk '{print $1}')
echo "[$(date)] DAILY backup OK: $DAILY_PATH ($SIZE)"

# По воскресеньям публикуем weekly-копию только после полного копирования.
if [ "$DAY_OF_WEEK" = "7" ]; then
    WEEKLY_PATH="$BACKUP_DIR/viewers.weekly.$DATE.${DAILY_PATH##*.}"
    "$PYTHON" "$SCRIPT_DIR/backup_storage.py" \
        --copy-archive "$DAILY_PATH" --destination "$WEEKLY_PATH" > /dev/null
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
