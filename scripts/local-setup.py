# -*- coding: utf-8 -*-
"""local-setup.py — поднять полную рабочую копию расширения на своём ПК.

ЗАЧЕМ. Пока версия расширения лежит на ревью Twitch, фронт заморожен, а прод
трогать не хочется. Локальная копия снимает оба ограничения: это тот же бэкенд и
тот же фронт, но на своём компьютере, и Twitch о нём ничего не знает.

Главное отличие от «просто запустить бэкенд»: база берётся из ВЧЕРАШНЕГО БЭКАПА
ПРОДА. То есть с настоящими зрителями, героями и ценами. Баги, которые вылезают
только на реальных данных, начинают ловиться до прода, а не после.

БАЗА КЛАДЁТСЯ ВНЕ РЕПОЗИТОРИЯ (%USERPROFILE%\\shedstream-local\\). Это не
придирка: 2026-06-25 локальная база рядом с кодом положила прод — её журнал
уехал в архив деплоя и затёр боевой. Снаружи репозитория этого не может
случиться в принципе.

ЗАПУСК:
    python scripts/local-setup.py            # развернуть/обновить копию
    python scripts/local-setup.py --keep     # не перезаписывать, если уже есть

Ничего на проде не трогает: читает только локальные файлы бэкапов.
Требует пакет zstandard (pip install zstandard).
"""
import argparse
import os
import pathlib
import shutil
import sqlite3
import sys

HOME = pathlib.Path(os.environ.get("USERPROFILE", os.path.expanduser("~")))
BACKUP_DIR = HOME / "shedstream-backups"
LOCAL_DIR = HOME / "shedstream-local"
LOCAL_DB = LOCAL_DIR / "viewers.db"

REPO = pathlib.Path(__file__).resolve().parent.parent
BACKEND = next((p / "backend" for p in REPO.iterdir()
                if (p / "backend").is_dir()), None)


def restore_latest(keep: bool) -> bool:
    try:
        import zstandard
    except ImportError:
        print("Нужен пакет zstandard:  pip install zstandard")
        return False

    snaps = sorted(BACKUP_DIR.glob("viewers.daily.*.db.zst"))
    if not snaps:
        print("Нет бэкапов в %s — сначала должен отработать забор." % BACKUP_DIR)
        return False
    src = snaps[-1]

    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    if LOCAL_DB.exists() and keep:
        print("Локальная база уже есть, оставляю как есть: %s" % LOCAL_DB)
        return True

    # Журналы от прошлого запуска — иначе SQLite подхватит чужой хвост.
    for suffix in ("-wal", "-shm", "-journal"):
        stale = LOCAL_DB.with_name(LOCAL_DB.name + suffix)
        if stale.exists():
            stale.unlink()

    print("Разжимаю %s ..." % src.name)
    with open(src, "rb") as fh, open(LOCAL_DB, "wb") as out:
        zstandard.ZstdDecompressor().copy_stream(fh, out)

    con = sqlite3.connect("file:%s?mode=ro" % LOCAL_DB.as_posix(), uri=True)
    try:
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            print("База битая — не буду ей пользоваться.")
            return False
        viewers = con.execute("SELECT COUNT(*) FROM viewers").fetchone()[0]
        chans = con.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
        row = con.execute("SELECT channel_id FROM channels LIMIT 1").fetchone()
        channel_id = row[0] if row else None
    finally:
        con.close()

    print("Готово: %s (%.0f МБ, зрителей %d, каналов %d)"
          % (LOCAL_DB, LOCAL_DB.stat().st_size / 1e6, viewers, chans))
    return channel_id


def ensure_env() -> pathlib.Path:
    """Локальный .env. Секреты выдуманные — они и должны быть выдуманными:
    это не прод, и настоящие сюда попадать не должны."""
    env_path = LOCAL_DIR / "local.env"
    if env_path.exists():
        print("Локальный .env уже есть: %s" % env_path)
        return env_path
    env_path.write_text(
        "# Локальная разработка. Значения ВЫДУМАННЫЕ и такими должны остаться:\n"
        "# настоящие прод-секреты сюда класть нельзя.\n"
        "TWITCH_OAUTH_TOKEN=local\n"
        "TWITCH_CLIENT_ID=local\n"
        "TWITCH_CLIENT_SECRET=local\n"
        "TWITCH_BOT_ID=local\n"
        "TWITCH_CHANNEL_NAME=localtest\n"
        "TWITCH_EXTENSION_SECRET=bG9jYWwtdGVzdC1zZWNyZXQtbm90LXJlYWwtMTIzNDU2\n"
        "MODULE_TOKEN_SECRET=local-module-secret-not-real\n"
        "ADMIN_PASSWORD=local\n"
        # Без неё миграция M1 отказывается стартовать (ей нужен канал для backfill).
        "TWITCH_BROADCASTER_ID=98319857\n"
        # Фоновые бэкапы локально не нужны: DB_PATH общий с backup_loop, и он
        # начал бы копировать рабочую копию (73 МБ) в папку репозитория.
        "BACKUP_INTERVAL_HOURS=100000\n",
        encoding="utf-8")
    print("Создал %s" % env_path)
    return env_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true",
                    help="не перезаписывать существующую локальную базу")
    args = ap.parse_args()

    if BACKEND is None:
        print("Не нашёл папку backend — запускай из репозитория.")
        return 1

    channel_id = restore_latest(args.keep)
    if channel_id is False:
        return 1
    env_path = ensure_env()

    print()
    print("=" * 68)
    print("ЧТО ДЕЛАТЬ ДАЛЬШЕ")
    print("=" * 68)
    print()
    print("1) Запустить локальный бэкенд (из папки backend):")
    print()
    print('   $env:DB_PATH = "%s"' % LOCAL_DB)
    print('   Get-Content "%s" | ForEach-Object {' % env_path)
    print('       if ($_ -and -not $_.StartsWith("#")) {')
    print('           $k,$v = $_ -split "=",2; Set-Item "env:$k" $v } }')
    print('   python main.py')
    print()
    print("2) Открыть в браузере:  http://127.0.0.1:8000/static/extension.html")
    print()
    print("3) Выдать токен поддельному моду (в другом окне, из папки backend):")
    print()
    print('   python -c "import sys; sys.path.insert(0,\'.\'); '
          'from routes.streamer import issue_module_token; '
          'print(issue_module_token(%s, \'rimworld\'))"'
          % (channel_id if channel_id else "98319857"))
    print()
    print("4) Натравить поддельный мод:")
    print()
    print("   python scripts/fake-mod.py --channel %s --token <токен>"
          % (channel_id if channel_id else "98319857"))
    print()
    print("Прод при этом не участвует нигде. База — копия, её не жалко.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
