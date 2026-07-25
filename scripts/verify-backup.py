# -*- coding: utf-8 -*-
"""verify-backup.py -- проверка, что офсайт-бэкап РЕАЛЬНО восстановим.

Задача Windows `shedstream-db-backup-pull` тянет суточный срез прод-базы на этот
ПК и пишет в лог «ok pulled». Но «файл скачался» != «из него можно поднять базу»:
архив мог приехать обрезанным, а внутри могла лежать база, снятая в момент
записи. Узнать об этом в день, когда бэкап понадобился, — худший вариант.

Скрипт разжимает свежий срез во временный файл, открывает его как SQLite,
гоняет integrity_check и проверяет, что ключевые таблицы на месте и не пустые.

    python scripts/verify-backup.py            # свежий срез
    python scripts/verify-backup.py --all      # все имеющиеся (долго)

Выход 0 = бэкап восстановим. Выход 1 = НЕ восстановим, разбираться сейчас.
Требует пакет zstandard (pip install zstandard).
"""
import argparse
import os
import pathlib
import sqlite3
import sys
import tempfile

BACKUP_DIR = pathlib.Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "shedstream-backups"

# Таблицы, потеря которых означает потерю проекта: зрители, их балансы, герои.
# Пустая таблица тут = бэкап снят с не той базы (мы уже ловили пустышки на проде).
REQUIRED_NONEMPTY = ["viewers"]
REQUIRED_PRESENT = ["bannerlord_heroes", "channels"]


def verify(path: pathlib.Path) -> bool:
    import zstandard

    print("  разжимаю %s (%.1f МБ)..." % (path.name, path.stat().st_size / 1e6))
    tmp = pathlib.Path(tempfile.gettempdir()) / ("_verify_" + path.stem)
    try:
        with open(path, "rb") as fh, open(tmp, "wb") as out:
            try:
                zstandard.ZstdDecompressor().copy_stream(fh, out)
            except zstandard.ZstdError as e:
                print("  FAIL: архив битый или обрезан: %s" % e)
                return False
        size = tmp.stat().st_size
        print("  распаковано: %.1f МБ" % (size / 1e6))
        if size < 1_000_000:
            print("  FAIL: подозрительно мало для прод-базы")
            return False

        con = sqlite3.connect("file:%s?mode=ro" % tmp.as_posix(), uri=True)
        try:
            res = con.execute("PRAGMA integrity_check").fetchone()[0]
            if res != "ok":
                print("  FAIL: integrity_check = %s" % res[:200])
                return False
            print("  integrity_check: ok")

            have = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            missing = [t for t in REQUIRED_PRESENT + REQUIRED_NONEMPTY if t not in have]
            if missing:
                print("  FAIL: нет таблиц: %s" % ", ".join(missing))
                return False
            print("  таблиц в базе: %d" % len(have))

            for t in REQUIRED_NONEMPTY:
                n = con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
                if n == 0:
                    print("  FAIL: таблица %s ПУСТА -- срез снят не с той базы" % t)
                    return False
                print("  %s: %d строк" % (t, n))
            for t in REQUIRED_PRESENT:
                n = con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
                print("  %s: %d строк" % (t, n))
        finally:
            con.close()
        return True
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="проверить все срезы, не только свежий")
    args = ap.parse_args()

    # «Не смог проверить» и «бэкап битый» -- разные новости. Не разведёшь их --
    # пропавший пакет каждый день кричит «бэкап сломан», на крик перестают
    # смотреть, и настоящую поломку тоже пропустят. Код 2 = проверить не вышло.
    try:
        import zstandard  # noqa: F401
    except ImportError:
        print("НЕ СМОГ ПРОВЕРИТЬ: нет пакета zstandard (pip install zstandard).")
        print("Это НЕ значит, что бэкап плохой -- значит, его никто не проверил.")
        return 2

    if not BACKUP_DIR.is_dir():
        print("НЕТ каталога бэкапов: %s" % BACKUP_DIR)
        return 1
    snaps = sorted(BACKUP_DIR.glob("viewers.daily.*.db.zst"))
    if not snaps:
        print("НЕТ срезов в %s -- забор не работает" % BACKUP_DIR)
        return 1

    targets = snaps if args.all else snaps[-1:]
    print("проверяю %d из %d срезов (свежий: %s)\n" % (len(targets), len(snaps), snaps[-1].name))

    bad = []
    for p in targets:
        print(p.name)
        try:
            ok = verify(p)
        except Exception as e:  # noqa: BLE001 -- любой сбой = бэкап под вопросом
            print("  FAIL: %s: %s" % (type(e).__name__, e))
            ok = False
        print("  => %s\n" % ("ВОССТАНОВИМ" if ok else "НЕ ВОССТАНОВИМ"))
        if not ok:
            bad.append(p.name)

    if bad:
        print("ИТОГ: битых срезов %d: %s" % (len(bad), ", ".join(bad)))
        return 1
    print("ИТОГ: все проверенные срезы восстановимы.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
