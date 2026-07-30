# -*- coding: utf-8 -*-
"""pack-audit.py — собрать пакет для независимого аудита сторонней моделью.

    python scripts/pack-audit.py

ЗАЧЕМ (2026-07-31). Пакет в `dist/audit/` собирался руками: архивы кода лежали
от 29.07, а к 31.07 их обогнали ~90 коммитов фиксов. Отдать такой пакет — значит
получить аудит кода, которого больше нет: часть находок будет про уже закрытое,
и на их разбор уйдёт проход целиком. Так и вышло с блоками S-01…S-15 из
предыдущего отчёта.

СВЕЖЕСТЬ АРХИВОВ — ЭТО НЕ УДОБСТВО, А ЕДИНСТВЕННЫЙ ЧЕСТНЫЙ СПОСОБ не повторять
находки. Правило проекта (CLAUDE.md §5b) запрещает писать проверяющему «сюда не
смотри, тут уже проверено»: указание уводит его ровно оттуда, где я мог
ошибиться. Значит убрать дубли можно только одним путём — дать актуальный код,
где закрытого попросту нет.

ЧТО КЛАДЁМ:
  0-BRIEF.md   — правила, приоритеты, мои ошибки как калибровка
  0-SPEC.md    — 17 блоков «инвариант / как ломается / где смотреть / чем проверить»
  1-frontend.zip, 2-backend.zip, 3-bannerlord-mod.zip — исходники
  MANIFEST.md  — коммит, дата, размеры, SHA-256 каждого архива

ЧТО НЕ КЛАДЁМ СОЗНАТЕЛЬНО: `STATUS.md`, `DEFERRED.md` и прошлые отчёты. Это
списки того, что уже найдено и починено, то есть тот самый запрет «не смотри
сюда», только в виде файла.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT = next((p for p in ROOT.iterdir() if (p / "backend").is_dir()), None)
OUT = ROOT / "dist" / "audit"

SKIP_PARTS = {"__pycache__", ".git", "node_modules", "venv"}
SKIP_SUFFIX = {".db", ".db-wal", ".db-shm", ".pyc", ".zip", ".log"}
SKIP_NAMES = {".env"}

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def _keep(p: Path) -> bool:
    if not p.is_file():
        return False
    if SKIP_PARTS & set(p.parts):
        return False
    if p.suffix in SKIP_SUFFIX or p.name in SKIP_NAMES:
        return False
    return True


def _zip(src: Path, dest: Path, patterns: tuple[str, ...]) -> int:
    n = 0
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for pat in patterns:
            for f in sorted(src.rglob(pat)):
                if _keep(f):
                    z.write(f, f.relative_to(src).as_posix())
                    n += 1
    return n


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if EXT is None:
        print("не нашёл каталог расширения (с backend/)")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)

    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()

    jobs = [
        ("1-frontend.zip", EXT / "frontend", ("*.html", "*.js", "*.css", "*.json")),
        ("2-backend.zip", EXT / "backend", ("*.py", "*.yaml", "*.html", "*.sh")),
        ("3-bannerlord-mod.zip", ROOT / "BannerlordLink" / "src", ("*.cs", "*.csproj")),
    ]
    rows = []
    for name, src, pats in jobs:
        if not src.is_dir():
            print(f"пропуск {name}: нет {src}")
            continue
        dest = OUT / name
        cnt = _zip(src, dest, pats)
        rows.append((name, cnt, dest.stat().st_size, _sha256(dest)))
        print(f"[ok] {name}: {cnt} файлов, {dest.stat().st_size // 1024} КБ")

    for doc, target in (("INDEPENDENT_AUDIT_BRIEF.md", "0-BRIEF.md"),
                        ("AUDIT_SPEC.md", "0-SPEC.md")):
        src = EXT / "docs" / doc
        if src.is_file():
            (OUT / target).write_text(src.read_text(encoding="utf-8"),
                                      encoding="utf-8")
            print(f"[ok] {target} <- docs/{doc}")

    manifest = [
        "# Пакет независимого аудита — манифест",
        "",
        f"- Собран: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"- Коммит: `{commit}`",
        f"- Рабочее дерево: {'ЕСТЬ НЕЗАКОММИЧЕННЫЕ ПРАВКИ' if dirty else 'чистое'}",
        "",
        "| Архив | Файлов | Байт | SHA-256 |",
        "|---|---:|---:|---|",
    ]
    for name, cnt, size, sha in rows:
        manifest.append(f"| {name} | {cnt} | {size} | `{sha}` |")
    manifest += [
        "",
        "## Что НЕ входит и почему",
        "",
        "`STATUS.md`, `DEFERRED.md` и прошлые отчёты об аудите намеренно НЕ",
        "включены. Это списки уже найденного — то есть указание «сюда не смотри»,",
        "только в виде файла. Правило проекта запрещает сообщать проверяющему,",
        "что уже проверено: оно уводит его оттуда, где мы могли ошибиться.",
        "",
        "Дубли убираются не запретами, а свежестью архивов: в коде выше",
        "закрытых дефектов уже нет, и повторить их находку не на чем.",
    ]
    (OUT / "MANIFEST.md").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    print(f"[ok] MANIFEST.md (коммит {commit[:8]}, дерево "
          f"{'ГРЯЗНОЕ' if dirty else 'чистое'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
