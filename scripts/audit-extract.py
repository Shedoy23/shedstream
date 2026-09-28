# -*- coding: utf-8 -*-
"""audit-extract.py — собрать выжимку кода для аудита сторонней моделью.

ЗАЧЕМ. Чтобы внешняя модель проверила код, ей нужно его увидеть. Целиком не
влезает: только `rimworld.py` — примерно 26 тысяч токенов, а в трёх «денежных»
файлах 11 тысяч строк. Отсюда естественный вывод «нужна подписка с доступом к
репозиторию» — и он неверный: собственно операций с деньгами в этих 11 тысячах
строк всего около полусотни.

Скрипт вырезает ровно три зоны риска с окрестностями, и результат помещается в
обычное окно бесплатного чата. Подписка не требуется.

Зоны выбраны те же, что в `docs/EXTERNAL_AUDIT_BRIEF.md`:
  1. деньги    — списания, начисления, возвраты и всё в радиусе;
  2. авторизация — ядро проверки прав целиком, оно небольшое;
  3. аренда    — запросы к таблицам, разделённым по каналам.

ЗАПУСК:
    python scripts/audit-extract.py                 # все три зоны
    python scripts/audit-extract.py --area money    # только деньги
    python scripts/audit-extract.py --context 40    # шире окрестности

Результат — файл `audit-extract.md` рядом со скриптом. Секретов не содержит:
`.env`, токены и ключи не читаются вообще.
"""
import argparse
import io
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
EXT = next((p for p in REPO.iterdir() if (p / "backend").is_dir()), None)
BACKEND = EXT / "backend" if EXT else None

MONEY_FILES = [
    "rimworld.py",
    "routes/bannerlord.py",
    "routes/bannerlord_diplomacy.py",
    "routes/bannerlord_family.py",
]
MONEY_PATTERN = re.compile(
    r"(remove_points|add_points|_charge_and_enqueue|refund|_enforce_price|price\s*=)")

AUTH_FILES = ["dependencies.py"]

TENANT_FILES = ["rimworld.py", "routes/bannerlord.py", "database.py"]
TENANT_PATTERN = re.compile(r"(INSERT INTO|UPDATE |DELETE FROM|SELECT .*FROM)")
TENANT_TABLES = ("viewers", "shop_catalog", "purchase_counters",
                 "rimworld_pending_commands", "bannerlord_heroes",
                 "rimworld_heal_cooldowns", "module_actions")


def cut(path: pathlib.Path, pattern: re.Pattern, context: int,
        must_contain=None) -> str:
    """Куски файла вокруг совпадений, слитые если пересекаются."""
    if not path.exists():
        return ""
    lines = io.open(path, encoding="utf-8", errors="replace").read().splitlines()
    hits = []
    for i, l in enumerate(lines):
        if not pattern.search(l):
            continue
        if must_contain and not any(t in l for t in must_contain):
            continue
        hits.append(i)
    if not hits:
        return ""

    spans = []
    for i in hits:
        lo, hi = max(0, i - context), min(len(lines), i + context + 1)
        if spans and lo <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], hi))
        else:
            spans.append((lo, hi))

    out = []
    for lo, hi in spans:
        out.append("\n--- строки %d-%d ---" % (lo + 1, hi))
        out.extend("%5d  %s" % (n + 1, lines[n]) for n in range(lo, hi))
    return "\n".join(out)


def whole(path: pathlib.Path) -> str:
    if not path.exists():
        return ""
    lines = io.open(path, encoding="utf-8", errors="replace").read().splitlines()
    return "\n".join("%5d  %s" % (i + 1, l) for i, l in enumerate(lines))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", choices=["money", "auth", "tenant", "all"],
                    default="all")
    ap.add_argument("--context", type=int, default=25,
                    help="сколько строк вокруг каждого совпадения")
    ap.add_argument("--out", default=str(REPO / "audit-extract.md"))
    args = ap.parse_args()

    if BACKEND is None:
        print("Не нашёл папку backend — запускай из репозитория.")
        return 1

    parts = ["# Выжимка кода для аудита",
             "",
             "Собрано автоматически: `python scripts/audit-extract.py`.",
             "Полные файлы не влезают в окно чата, поэтому вырезаны только три",
             "зоны риска с окрестностями. Нумерация строк — как в исходных файлах.",
             "",
             "Что искать и в каком формате отвечать — в `docs/EXTERNAL_AUDIT_BRIEF.md`.",
             ""]

    if args.area in ("money", "all"):
        parts += ["", "## 1. Деньги", "",
                  "Списания, начисления, возвраты и код вокруг них.",
                  "Вопрос: может ли зритель заплатить и не получить результат;",
                  "получить, не заплатив; заплатить дважды за одно; получить",
                  "возврат дважды.", ""]
        for f in MONEY_FILES:
            body = cut(BACKEND / f, MONEY_PATTERN, args.context)
            if body:
                parts += ["", "### %s" % f, "```python", body, "```"]

    if args.area in ("auth", "all"):
        parts += ["", "## 2. Авторизация", "",
                  "Ядро проверки прав целиком — оно небольшое. Имя зрителя и",
                  "канал должны браться из подписанного токена, а не из тела",
                  "запроса. Вопрос: может ли зритель действовать от чужого имени",
                  "или в чужом канале.", ""]
        for f in AUTH_FILES:
            body = whole(BACKEND / f)
            if body:
                parts += ["", "### %s (целиком)" % f, "```python", body, "```"]

    if args.area in ("tenant", "all"):
        parts += ["", "## 3. Разделение каналов", "",
                  "Запросы к таблицам, которые обязаны быть разделены по",
                  "`channel_id`. Вопрос: может ли запрос вернуть или изменить",
                  "данные чужого канала.", ""]
        for f in TENANT_FILES:
            body = cut(BACKEND / f, TENANT_PATTERN, 6, must_contain=TENANT_TABLES)
            if body:
                parts += ["", "### %s" % f, "```python", body, "```"]

    text = "\n".join(parts)
    out = pathlib.Path(args.out)
    io.open(out, "w", encoding="utf-8", newline="\n").write(text)

    chars = len(text)
    print("Готово: %s" % out)
    print("  %d символов ≈ %d токенов, строк %d"
          % (chars, chars // 4, text.count("\n")))
    if chars // 4 > 30000:
        print("  ВЕЛИКОВАТО для одного сообщения — уменьши --context")
        print("  или собирай по одной зоне: --area money")
    else:
        print("  влезает в одно сообщение обычного чата")
    return 0


if __name__ == "__main__":
    sys.exit(main())
