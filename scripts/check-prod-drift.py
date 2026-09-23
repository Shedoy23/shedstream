"""check-prod-drift.py — есть ли на проде backend-код, которого эта ветка никогда не видела.

Зачем. `deploy.ps1 -Backend` распаковывает локальный backend поверх прода.
Если прод выкатывали из ДРУГОЙ ветки (хотфикс из соседнего worktree), выкат из
этой молча откатит те правки. 23.09 внешний аудит нашёл ровно это: выкат из
`codex-public-release` снёс бы защиту перековки и откат ежедневной награды —
они жили в `claude/poststream-2026-09-22`, а не в той ветке.

Как. Для каждого .py на проде берётся git-хеш его содержимого (CRLF → LF).
Если такое содержимое есть в истории HEAD или совпадает с рабочей копией —
эта ветка его знает, выкат ничего не потеряет. Иначе — «чужая» версия.

    python scripts/check-prod-drift.py            # прод
    python scripts/check-prod-drift.py --ref codex/public-release-readiness

Код возврата: 0 — чужого кода нет; 1 — есть (список напечатан); 2 — не смог проверить.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
BACKEND_REL = "Расширение/backend"
PROD_HOST = "root@31.130.132.224"
PROD_BACKEND = "/root/twitch-extension/backend"

# Runs on the server: prints "<git blob sha of LF-normalized content> <path>".
REMOTE = r'''
import hashlib, os
for d, dirs, files in os.walk("."):
    dirs[:] = [x for x in dirs if x not in ("venv", ".venv", "__pycache__")]
    for f in files:
        if f.endswith(".py"):
            p = os.path.join(d, f)
            b = open(p, "rb").read().replace(b"\r\n", b"\n")
            print(hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest(), p[2:].replace(os.sep, "/"))
'''


def blob_sha(data: bytes) -> str:
    data = data.replace(b"\r\n", b"\n")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="HEAD", help="ветка/коммит, из которого собираемся выкатывать")
    ap.add_argument("--host", default=PROD_HOST)
    ap.add_argument("--dir", default=PROD_BACKEND)
    a = ap.parse_args()

    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", a.host,
                            f"cd {a.dir} && python3 -"], input=REMOTE, capture_output=True,
                           text=True, encoding="utf-8", timeout=120)
        if r.returncode != 0 or not r.stdout.strip():
            print(f"[drift] не смог прочитать прод: {r.stderr.strip()[:300]}")
            return 2
        known = {line.split()[0] for line in
                 git("rev-list", "--objects", a.ref, "--", BACKEND_REL).splitlines()}
    except Exception as e:  # noqa: BLE001 — any failure here means "not checked"
        print(f"[drift] проверка не выполнена: {e}")
        return 2

    foreign, orphans = [], []
    for line in r.stdout.splitlines():
        sha, rel = line.split(" ", 1)
        local = ROOT / BACKEND_REL / rel
        in_tree = a.ref == "HEAD" and local.exists()  # the tree is only HEAD's working copy
        if sha in known or (in_tree and blob_sha(local.read_bytes()) == sha):
            if a.ref == "HEAD" and not local.exists():
                orphans.append(rel)
            continue
        foreign.append(rel)

    if orphans:
        print(f"[drift] на проде {len(orphans)} файл(ов), удалённых в ветке (остались от "
              f"старых выкатов, выкат их не трогает): {', '.join(sorted(orphans))}")
    if foreign:
        print(f"[drift] СТОП: на проде {len(foreign)} файл(ов) с кодом, которого нет в "
              f"истории {a.ref}. Выкат откатит эти правки:")
        for rel in sorted(foreign):
            print(f"  - {rel}")
        print("[drift] Сначала влей ветку, из которой выкатывали прод (подсказка: "
              "git branch -a --contains <коммит>), потом выкатывай.")
        return 1
    print(f"[drift] ok: весь backend-код прода известен {a.ref}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
