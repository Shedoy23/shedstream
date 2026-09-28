"""
test_contest_rules_and_prize.py — правила конкурса на месте, приз без случайности.

Standalone (без pytest). Запуск из backend/:
    python tests/test_contest_rules_and_prize.py

ЗАЧЕМ. Аудит 002 (29.08) нашёл два основания для отказа, не связанных с
правилом 3.5 и потому незамеченных:

1. **R1 — правил конкурса нет нигде.** Расширение объявляет окончание сезона,
   три призовых места и порог рейтинга, а App Store Review 5.3.2 требует, чтобы
   официальные правила были показаны В САМОМ приложении и чтобы там прямо
   стояло, что Apple не является спонсором. Ни одного слова про правила во
   фронте не было — проверено грепом.
2. **B6 — генератор случайного турнирного трофея жив.** Кузницу сняли с продажи
   29.07 и убрали раскрытие её шансов, а `generate_prize_item()` продолжал
   катать редкость 50/30/15/5 и характеристики победителю турнира. То есть наше
   же заявление ревьюеру «единственная случайность — тир кейса» было неверным.
   Предмет при этом никуда не показывался: `/api/bannerlord/custom-items` во
   фронте не зовётся, а `hero.equip_trophy` снят с продажи.

Тест держит три границы:

1. **Правила есть в ОБЕИХ оболочках и совпадают дословно.** Оболочки
   расходятся молча, и разошедшийся юридический текст хуже отсутствующего.
2. **Обязательные формулировки на месте** — бесплатный вход и «Apple не
   спонсор» на двух языках: ревьюер читает по-английски.
3. **На пути к призу нет ни одного вызова случайности.** Проверяется не текст
   комментария, а отсутствие символов: `generate_prize_item` не существует в
   бэкенде, адаптер не импортирует модуль кастомных предметов, а описание
   турнира во фронте не обещает «приз».
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

HERE = Path(__file__).parent.absolute()
BACKEND = HERE.parent
FRONTEND = BACKEND.parent / "frontend"

failures: list[str] = []


def check(ok: bool, what: str, detail: str = "") -> None:
    if ok:
        print(f"  ✅ {what}")
    else:
        print(f"  ❌ {what}{(' — ' + detail) if detail else ''}")
        failures.append(what)


def extract_rules(html: str) -> str:
    """Вырезать блок правил целиком. Пусто = блока нет."""
    m = re.search(r'<details id="contest-rules".*?</details>', html, re.S)
    return m.group(0) if m else ""


print("=" * 70)
print("1. Официальные правила конкурса в интерфейсе (Apple 5.3.2)")
print("=" * 70)

shells = {name: (FRONTEND / name).read_text(encoding="utf-8")
          for name in ("extension.html", "mobile.html")}
blocks = {name: extract_rules(html) for name, html in shells.items()}

for name, block in blocks.items():
    check(bool(block), f"{name}: блок #contest-rules присутствует",
          "правил конкурса нет — это отдельное основание для отказа")

if all(blocks.values()):
    check(blocks["extension.html"] == blocks["mobile.html"],
          "текст правил в обеих оболочках совпадает дословно",
          "оболочки разошлись — часть аудитории увидит другие правила")

    # Формулировки, которых требует именно ревью, а не наш вкус.
    required = [
        ("Apple is not a sponsor", "Apple не спонсор (EN — читает ревьюер)"),
        ("Apple не является спонсором", "Apple не спонсор (RU)"),
        ("No purchase", "вход бесплатный (EN)"),
        ("покупка не требуется", "вход бесплатный (RU)"),
        ("no monetary value", "призы без денежной ценности (EN)"),
        ("не имеют денежной ценности", "призы без денежной ценности (RU)"),
    ]
    for needle, what in required:
        check(all(needle in b for b in blocks.values()), f"в правилах есть: {what}",
              f"не найдено «{needle}»")

print()
print("=" * 70)
print("2. Турнирный приз не разыгрывается (аудит 002, B6)")
print("=" * 70)

# tests/ исключён намеренно: этот файл сам называет символ в описании,
# и без исключения проверка всегда находила бы саму себя.
py_files = [p for p in BACKEND.rglob("*.py")
            if "__pycache__" not in p.parts and "tests" not in p.parts]
def code_only(src: str) -> str:
    """Отбросить хвосты-комментарии: объяснение, ПОЧЕМУ механику убрали, —
    ценность, а не нарушение. Запрещён живой символ, а не память о нём."""
    return " ".join(line.split("#", 1)[0] for line in src.splitlines())


hits = [f"{p.relative_to(BACKEND)}" for p in py_files
        if "generate_prize_item" in code_only(
            p.read_text(encoding="utf-8", errors="replace"))]
check(not hits, "generate_prize_item не существует в бэкенде (в коде, не в комментарии)",
      ", ".join(hits))

adapter = (BACKEND / "modules" / "bannerlord" / "_adapter.py").read_text(encoding="utf-8")
check("bannerlord_custom_items" not in adapter,
      "адаптер Bannerlord не трогает кастомные предметы",
      "остался импорт — значит, приз всё ещё генерируется")
check("insert_custom_item" not in adapter,
      "адаптер не вставляет предмет победителю турнира")

viewer = (FRONTEND / "viewer-bannerlord.js").read_text(encoding="utf-8")
m = re.search(r"победитель получает[^`]*", viewer)
check(bool(m), "описание турнира найдено во фронте")
if m:
    check("приз" not in m.group(0),
          "описание турнира не обещает «приз»",
          f"обещает: {m.group(0)[:120]}")

print()
print("=" * 70)
if failures:
    print(f"ПРОВАЛ: {len(failures)} проверок")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("ВСЁ ЗЕЛЁНОЕ")
sys.exit(0)
