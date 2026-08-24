# -*- coding: utf-8 -*-
"""Доказательство, что сокращение не потеряло содержания.

Идея: сокращать текст можно честно (то же знание короче) и нечестно (знание
исчезло). Отличить одно от другого на глаз нельзя — 10 000 символов разницы
никто не вычитает. Поэтому проверяем механически: каждый ИМЕНОВАННЫЙ объект из
оригиналов (файл, функция, флаг, таблица, порог, команда) обязан встречаться
либо в новом CLAUDE.md, либо в LESSONS.md. Пропажа имени = пропажа знания.
"""
import pathlib, re, sys

S = pathlib.Path(sys.argv[1])
orig = [(S / "claude-project.orig"), (S / "claude-personal.orig")]
new = [pathlib.Path("C:/Users/Edward/Desktop/work/CLAUDE.md"),
       pathlib.Path("C:/Users/Edward/.claude/CLAUDE.md"),
       pathlib.Path("C:/Users/Edward/Desktop/work/LESSONS.md")]

corpus = "\n".join(p.read_text(encoding="utf-8") for p in new)

def tokens(text):
    out = set()
    # 1. всё в обратных кавычках — имена файлов, функций, флагов, команд
    out |= {m.strip() for m in re.findall(r"`([^`\n]{2,120})`", text)}
    # 2. числа с разделителями и порогами — цены, лимиты, окна
    out |= set(re.findall(r"\b\d[\d_ ]{2,}\b", text))
    # 3. ЗАГЛАВНЫЕ маркеры-термины
    out |= {w for w in re.findall(r"\b[A-Z][A-Z_]{4,}\b", text)}
    return out

missing_all = {}
for p in orig:
    text = p.read_text(encoding="utf-8")
    miss = sorted(t for t in tokens(text) if t not in corpus)
    if miss:
        missing_all[p.name] = miss

for name, miss in missing_all.items():
    print(f"\n{name}: не найдено в новых файлах — {len(miss)}")
    for m in miss:
        print("   ·", m)

total = sum(len(m) for m in missing_all.values())
print("\n" + "=" * 60)
if total:
    print(f"ПОТЕРЯНО ИМЁН: {total}")
    sys.exit(1)
print("Все именованные объекты из оригиналов присутствуют")
sys.exit(0)
