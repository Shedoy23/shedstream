# -*- coding: utf-8 -*-
"""Проверка, что сокращение файла правил не потеряло содержания.

    python scripts/check-rules-coverage.py [ревизия-до]     # по умолчанию HEAD~1

ЗАЧЕМ. Сокращать текст правил можно честно (то же знание короче) и нечестно
(знание исчезло). На глаз это не различается: десять тысяч символов разницы
никто не вычитывает, а пропавшее правило не подаёт признаков — оно просто
перестаёт соблюдаться через месяц. 24.08 при разделении CLAUDE.md на «что
делать» и LESSONS.md («почему») эта проверка нашла реальную потерю: исчезли
HTML-маркеры CODEGRAPH_START/END, по которым CLI обновляет свой блок, — то
есть следующее обновление приписало бы второй блок вместо правки первого.

КАК. Из версии «до» вытаскиваются ИМЕНОВАННЫЕ объекты — всё в обратных
кавычках (файлы, функции, флаги, таблицы, команды), крупные числа (цены,
лимиты, окна) и КОНСТАНТЫ_КАПСОМ. Каждое имя обязано найтись в текущих
файлах правил. Пропажа имени = пропажа знания; пересказ своими словами
проверку проходит, а тихое выбрасывание — нет.

ЧЕГО ПРОВЕРКА НЕ ЛОВИТ (важно, чтобы зелёный прогон не читался шире, чем он
есть): потерю мысли, у которой нет имени. Если правило было «не делай X,
потому что Y», и его выкинули целиком, но ни одного имени в нём не было —
здесь будет зелено. Заголовки правил поэтому смотреть глазами.
"""
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RULES_FILE = "CLAUDE.md"
# Куда содержание могло законно переехать при сокращении.
CURRENT = [ROOT / "CLAUDE.md", ROOT / "LESSONS.md",
           pathlib.Path.home() / ".claude" / "CLAUDE.md"]


def names(text):
    out = set()
    out |= {m.strip() for m in re.findall(r"`([^`\n]{2,120})`", text)}
    out |= set(re.findall(r"\b\d[\d_ ]{2,}\b", text))
    out |= {w for w in re.findall(r"\b[A-Z][A-Z_]{4,}\b", text)}
    return out


def main():
    rev = sys.argv[1] if len(sys.argv) > 1 else "HEAD~1"
    try:
        before = subprocess.run(
            ["git", "-C", str(ROOT), "show", f"{rev}:{RULES_FILE}"],
            capture_output=True, check=True).stdout.decode("utf-8", "replace")
    except subprocess.CalledProcessError as e:
        print(f"[rules] не читается {rev}:{RULES_FILE}: "
              f"{e.stderr.decode('utf-8', 'replace').strip()}")
        return 2

    corpus = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                       for p in CURRENT if p.is_file())
    missing = sorted(n for n in names(before) if n not in corpus)

    print(f"[rules] сравниваю {rev}:{RULES_FILE} с текущими правилами "
          f"({len(names(before))} именованных объектов)")
    for m in missing:
        print(f"[rules][ERROR] пропало при сокращении: {m}")
    if missing:
        print(f"[rules] ПРОВАЛЕНО: потеряно {len(missing)}")
        return 1
    print("[rules] OK: все именованные объекты на месте")
    return 0


if __name__ == "__main__":
    sys.exit(main())
