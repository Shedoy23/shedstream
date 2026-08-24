# -*- coding: utf-8 -*-
"""Ищет один и тот же текст, живущий в двух файлах документации.

Почему это дефект: у копии нет владельца. Правят один экземпляр, второй
остаётся и продолжает выглядеть верным — отличить копию от оригинала по виду
нельзя. Ровно так «RUNBOOK §2c» пережил перенумерацию, а «viewer.js ~7k»
дважды пересказали владельцу как факт.

Метод: файл режется на блоки (абзац или пункт списка), блок нормализуется
(маркдаун, регистр, пунктуация — прочь), сравниваются множества 4-словных
сочетаний. Совпадение >= порога и блок длиннее 12 слов — кандидат в дубли.
"""
import itertools
import pathlib
import re
import sys

ROOT = pathlib.Path("C:/Users/Edward/Desktop/work")
FILES = ["CLAUDE.md", "LESSONS.md", "RUNBOOK.md", "STATUS.md", "DEFERRED.md",
         "ROADMAP.md", "OVERVIEW.md", "scripts/README.md",
         "Расширение/docs/CONTEXT.md", "Расширение/docs/CONTEXT_BANNERLORD.md",
         "Расширение/docs/CONTEXT_RIMWORLD.md",
         "Расширение/docs/TWITCH_UPDATE_RELEASE_PLAYBOOK.md"]
PERSONAL = pathlib.Path.home() / ".claude" / "CLAUDE.md"

THRESHOLD = float(sys.argv[1]) if len(sys.argv) > 1 else 0.55
MIN_WORDS = 12


def blocks(text):
    out = []
    for raw in re.split(r"\n\s*\n", text):
        for piece in re.split(r"\n(?=\s*(?:[-*]|\d+\.)\s)", raw):
            piece = piece.strip()
            if piece.startswith("#") or piece.startswith("```"):
                continue
            words = norm(piece)
            if len(words) >= MIN_WORDS:
                out.append((piece, shingles(words)))
    return out


def norm(s):
    s = re.sub(r"`[^`]*`", " ", s)          # код не считаем: пути совпадают законно
    s = re.sub(r"[*_>#\[\]()«»„“”\-—:;,.!?/\\|]", " ", s.lower())
    return [w for w in s.split() if len(w) > 2]


def shingles(words, n=4):
    return {tuple(words[i:i + n]) for i in range(max(1, len(words) - n + 1))}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


docs = {}
for name in FILES:
    p = ROOT / name
    if p.is_file():
        docs[name] = blocks(p.read_text(encoding="utf-8", errors="replace"))
if PERSONAL.is_file():
    docs["~/.claude/CLAUDE.md"] = blocks(PERSONAL.read_text(encoding="utf-8", errors="replace"))

pairs = []
for (fa, ba), (fb, bb) in itertools.combinations(docs.items(), 2):
    for ta, sa in ba:
        for tb, sb in bb:
            j = jaccard(sa, sb)
            if j >= THRESHOLD:
                pairs.append((j, fa, fb, ta, tb))

pairs.sort(reverse=True, key=lambda x: x[0])

# Храповик: столько пар было на 2026-08-24, когда дедупликацию довели до нуля.
# Растёт — значит завели новую копию; падает — можно опустить планку здесь.
BUDGET = 0
print(f"порог {THRESHOLD}, блоков всего {sum(len(v) for v in docs.values())}")
print(f"пар-дублей: {len(pairs)}\n")
by_pair = {}
for j, fa, fb, ta, tb in pairs:
    by_pair.setdefault((fa, fb), []).append((j, ta, tb))
for (fa, fb), items in sorted(by_pair.items(), key=lambda kv: -len(kv[1])):
    print(f"=== {fa}  <->  {fb}: {len(items)}")
    for j, ta, tb in items[:4]:
        print(f"    {j:.2f}  {ta[:96].replace(chr(10), ' ')}")

if len(pairs) > BUDGET:
    print("")
    print(f"[docs][ERROR] копий стало больше: {len(pairs)} при бюджете {BUDGET}.")
    print("У каждого утверждения должен быть один дом; в остальных файлах — ссылка.")
    print("Копия не имеет владельца: правят одну, вторая продолжает выглядеть верной.")
    raise SystemExit(1)
print("[docs] OK: новых копий нет")
raise SystemExit(0)
