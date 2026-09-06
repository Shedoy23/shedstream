# -*- coding: utf-8 -*-
"""Что у нас уже написано по теме — один вызов вместо серии grep'ов.

    python scripts/docs-search.py фолловеры eventsub
    python scripts/docs-search.py "пул соединений"
    python scripts/docs-search.py бэкап --full

ЗАЧЕМ. Самый частый дорогой промах этого проекта — заново расследовать то, что
уже записано. Токен Twitch кричал в лог три недели, офсайт-бэкап числился
дырой месяц после того, как был сделан, `MOD_CONTRACT.md` существовал, но на
него не ссылался никто. Документация выросла до ~330 тысяч знаков в дюжине
файлов: grep по одному файлу её уже не покрывает, а читать всё — дороже задачи.

ЧТО ДЕЛАЕТ. Ищет по всему набору документов сразу и показывает НЕ строку, а
РАЗДЕЛ, в котором она лежит — видно, чей это дом и куда писать продолжение.
Ранжирует по числу совпавших слов; тема в заголовке весит больше упоминания
в тексте.

КОГДА ЗАПУСКАТЬ. Перед новой механикой, перед починкой в незнакомой области и
на любом вопросе вида «почему X сломан» — до того, как открывать код. Нашлось
— читать найденное; не нашлось — так и сказать в сводке: это тоже результат,
значит тему надо описать по ходу.
"""
import pathlib
import re
import sys

# Консоль Windows отдаёт cp1251: без этого скрипт печатал кракозябры, а на
# первом же «→» падал с UnicodeEncodeError — то есть по документации нельзя
# было искать из PowerShell вообще. Тот же дефект чинили в pack-extension.py.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ["CLAUDE.md", "LESSONS.md", "RUNBOOK.md", "STATUS.md", "DEFERRED.md",
        "ROADMAP.md", "OVERVIEW.md", "scripts/README.md"]
DOC_DIRS = ["Расширение/docs", "docs"]
CONTEXT_CHARS = 260


def collect():
    out = []
    for rel in DOCS:
        p = ROOT / rel
        if p.is_file():
            out.append(p)
    for d in DOC_DIRS:
        base = ROOT / d
        if base.is_dir():
            out += [p for p in sorted(base.rglob("*.md")) if "archive" not in p.parts]
    return out


def stem(word):
    """Грубо срезать окончание: «фолловеры» -> «фолловер».

    Усекаем ТОЛЬКО слово запроса, а в тексте ищем подстрокой: если усекать обе
    стороны, «фолловеры» даёт «фолловер», а «фолловеров» — «фоллов», и слово
    перестаёт находить само себя в другом падеже.
    """
    w = word.lower()
    for suf in ("ами", "ями", "ов", "ев", "ах", "ях", "ые", "ий", "ой", "ая",
                "ы", "и", "а", "у", "е", "ю", "я", "ь"):
        if len(w) > 5 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def sections(path):
    """Разрезать документ на разделы по заголовкам."""
    lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
    bounds = [i for i, l in enumerate(lines) if l.startswith("#")]
    if not bounds or bounds[0] != 0:
        bounds = [0] + bounds
    for k, start in enumerate(bounds):
        end = bounds[k + 1] if k + 1 < len(bounds) else len(lines)
        first = lines[start]
        heading = first.lstrip("# ").strip() if first.startswith("#") else ""
        yield start, heading, lines[start:end]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    full = "--full" in sys.argv
    if not args:
        print("укажи тему: python scripts/docs-search.py <слова>")
        return 2
    # Слова запроса режем по \\w+ и ищем подстроками: «no-op» в тексте лежит
    # целиком, но по \\w+ распадается на «no» и «op».
    terms = [stem(w) for w in re.findall(r"\w+", " ".join(args).lower())]
    need = (len(terms) + 1) // 2      # половина слов: одно — почти всегда шум

    hits = []
    for path in collect():
        for start, heading, body_lines in sections(path):
            body = "\n".join(body_lines).lower()
            matched = [t for t in terms if t in body]
            if len(matched) < need:
                continue
            score = len(matched) * 10 + (5 if len(matched) == len(terms) else 0)
            if heading and any(t in heading.lower() for t in terms):
                score += 8        # тема в заголовке — это её дом, а не упоминание
            best_line, best_n, best_off = "", -1, 0
            for off, line in enumerate(body_lines):
                n = sum(1 for t in terms if t in line.lower())
                if line.strip() and n > best_n:
                    best_line, best_n, best_off = line.strip(), n, off
            hits.append((score, path, start + best_off, heading, best_line,
                         len(matched)))

    if not hits:
        print(f"по теме «{' '.join(args)}» в документации НИЧЕГО не найдено.")
        print("Это результат: тема не описана — опиши её по ходу задачи.")
        return 1

    hits.sort(key=lambda h: -h[0])
    limit = len(hits) if full else 12
    complete = sum(1 for h in hits if h[5] == len(terms))

    print(f"по теме «{' '.join(args)}» — {len(hits)} разделов, "
          f"со ВСЕМИ словами: {complete} "
          f"(показаны {min(limit, len(hits))}; --full для всех)")
    if len(terms) > 1 and not complete:
        print("ВНИМАНИЕ: ни в одном разделе не совпали все слова — вероятно, "
              "тема не описана, а ниже просто отдельные слова.")
    print()

    for score, path, line_no, heading, line, _ in hits[:limit]:
        rel = path.relative_to(ROOT).as_posix()
        print(f"[{score:>3}] {rel}:{line_no + 1}")
        if heading:
            print(f"      раздел: {heading}")
        print(f"      {line[:CONTEXT_CHARS]}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
