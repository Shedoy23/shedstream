# -*- coding: utf-8 -*-
"""audit_dead_code.py — след вырезанных механик: что осталось без входа.

ЗАЧЕМ. 2026-07-29 за один день нашлись четыре механики, вырезанные наполовину:
рента с феодов, ковка и трофеи, аукцион кованых предметов, «рулекцион». Почерк
один — механику выключают там, где она РАБОТАЕТ, и не выключают там, где она
ПРОДАЁТСЯ или опрашивается. Три из четырёх оказались не мёртвым кодом, а живой
задней дверью: путём, которым зритель может потратить крустики на то, чего
официально нет.

Ни один тест такого не ловит: с их точки зрения ничего не сломалось.

ЧТО ДЕЛАЕТ. Четыре независимые проверки, каждая печатает список КАНДИДАТОВ:

  1. Маршруты без потребителя — путь не упоминается ни во фронте, ни в
     шаблонах страниц стримера, ни в исходниках модов (моды зовут бэкенд сами).
  2. Файлы фронта, не подключённые ни в одном шелле.
  3. Таблицы базы, к которым никто не обращается вне миграций.
  4. Константы конфига без потребителей.

ЧТО ЭТО НЕ ДЕЛАЕТ. Не выносит приговор. Кандидат — повод посмотреть, а не
удалить: маршрут может звать сторонний инструмент, таблицу может писать
миграция ради истории. Решение всегда за человеком.

Запуск:  python scripts/audit_dead_code.py
Код возврата всегда 0 — это отчёт, а не гейт.
"""
import ast
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXT = next((p for p in ROOT.iterdir() if (p / "backend").is_dir()), None)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def _read(p: pathlib.Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _consumer_blob() -> str:
    """Всё, что может ВЫЗЫВАТЬ бэкенд: фронт, шаблоны страниц, моды."""
    parts = []
    for sub, patterns in (
        (EXT / "frontend", ("*.js", "*.html")),
        (EXT / "backend" / "templates", ("*.html",)),
        (ROOT / "BannerlordLink" / "src", ("*.cs",)),
        (ROOT / "RimLink", ("*.cs",)),
        (ROOT / "scripts", ("*.py", "*.ps1")),
    ):
        if not sub.exists():
            continue
        for pattern in patterns:
            for f in sub.rglob(pattern):
                parts.append(_read(f))
    return "\n".join(parts)


# Маршруты, которые ПО ЗАМЫСЛУ зовёт не панель зрителя. Отсутствие во фронте
# для них норма, а не находка: их дёргают Twitch (вебхуки), моды в играх,
# страница стримера по cookie-сессии, админ-инструменты. Показываем отдельным
# списком — чтобы кандидаты не тонули в шуме, но и служебные не прятались.
_SERVICE_PREFIXES = (
    "/eventsub",
    "/v1/",
    "/api/admin/",
    "/dev/",
    "/api/streamer/",
    "/api/overlay/",
)


def _mounted_paths():
    """Пути, реально подключённые к приложению.

    Файл с @router может лежать в репозитории, а роутер быть НЕ подключён в
    main.py — тогда маршрута не существует и в отчёт он попадать не должен.
    Ровно так вышло с аукционом кованых предметов после его отключения.
    """
    backend = EXT / "backend"
    saved = dict(os.environ)
    for k, v in {
        "TWITCH_OAUTH_TOKEN": "oauth:t", "TWITCH_CLIENT_ID": "c",
        "TWITCH_CLIENT_SECRET": "s", "TWITCH_BOT_ID": "b",
        "TWITCH_EXTENSION_SECRET": "audit-secret-32bytes-1234567890abcd",
        "MODULE_TOKEN_SECRET": "audit-module-secret-32bytes-1234567",
        "ADMIN_PASSWORD": "audit_only_password_not_used_anywhere",
        "TWITCH_BROADCASTER_ID": "1",
    }.items():
        os.environ.setdefault(k, v)
    sys.path.insert(0, str(backend))
    cwd = os.getcwd()
    try:
        os.chdir(backend)
        import importlib
        main_mod = importlib.import_module("main")
        return {r.path for r in main_mod.app.routes if hasattr(r, "path")}
    except Exception as e:
        print(f"    (приложение не поднялось: {type(e).__name__}: {e};"
              f" проверка идёт по файлам, возможны ложные срабатывания)")
        return None
    finally:
        os.chdir(cwd)
        os.environ.clear()
        os.environ.update(saved)


def routes_without_consumer(blob: str):
    """Маршруты, которых никто не зовёт. Возвращает (кандидаты, служебные)."""
    backend = EXT / "backend"
    mounted = _mounted_paths()
    candidates, service = [], []
    route_re = re.compile(r'@router\.(get|post|put|delete|patch)\(\s*[\'"]([^\'"]+)[\'"]')
    for f in sorted(backend.rglob("*.py")):
        if "__pycache__" in str(f) or "migrations" in str(f):
            continue
        src = _read(f)
        for m in route_re.finditer(src):
            path = m.group(2)
            if mounted is not None and path not in mounted:
                continue          # роутер не подключён — маршрута нет
            needle = path.split("{")[0].rstrip("/")
            if not needle or needle == "/api":
                continue
            if needle in blob:
                continue
            line = src[:m.start()].count("\n") + 1
            row = (f.relative_to(ROOT).as_posix(), line, m.group(1).upper(), path)
            # Админский эндпоинт зовут руками или скриптом, а не панелью —
            # это служебное, даже если путь не начинается с /api/admin/.
            tail = src[m.end():m.end() + 400]
            is_admin = "require_admin" in tail
            is_service = path.startswith(_SERVICE_PREFIXES) or is_admin
            (service if is_service else candidates).append(row)
    return candidates, service


def frontend_files_not_included():
    """Файлы фронта, не подключённые ни в одном шелле."""
    frontend = EXT / "frontend"
    if not frontend.exists():
        return []
    shells = "\n".join(_read(f) for f in frontend.glob("*.html"))
    orphans = []
    for f in sorted(frontend.glob("*.js")):
        if f.name not in shells:
            orphans.append(f.relative_to(ROOT).as_posix())
    return orphans


def tables_without_users():
    """Таблицы, упомянутые только в миграциях и нигде в коде."""
    backend = EXT / "backend"
    tables = set()
    create_re = re.compile(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+([a-z_][a-z0-9_]*)",
                           re.IGNORECASE)
    for f in sorted((backend / "migrations").rglob("*.py")):
        for m in create_re.finditer(_read(f)):
            tables.add(m.group(1).lower())
    for m in create_re.finditer(_read(backend / "database.py")):
        tables.add(m.group(1).lower())

    code = []
    for f in sorted(backend.rglob("*.py")):
        if "__pycache__" in str(f) or "migrations" in str(f):
            continue
        code.append(_read(f))
    code_blob = "\n".join(code)

    dead = []
    for t in sorted(tables):
        # Ищем таблицу в запросах вне миграций: FROM/INTO/UPDATE/JOIN.
        if re.search(r"\b(FROM|INTO|UPDATE|JOIN|TABLE)\s+" + re.escape(t) + r"\b",
                     code_blob, re.IGNORECASE):
            continue
        dead.append(t)
    return dead


def config_constants_without_users():
    """Константы верхнего уровня в config.py, которых никто не читает."""
    backend = EXT / "backend"
    cfg = backend / "config.py"
    src = _read(cfg)
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    names = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper() and len(t.id) > 3:
                    names.append(t.id)

    blob = []
    for f in sorted(backend.rglob("*.py")):
        if "__pycache__" in str(f) or f.name == "config.py":
            continue
        blob.append(_read(f))
    blob = "\n".join(blob) + "\n" + "\n".join(
        _read(f) for f in (EXT / "frontend").glob("*.js"))

    return [n for n in names if n not in blob]


def main() -> int:
    if EXT is None:
        print("не нашёл каталог расширения (с backend/)")
        return 0

    blob = _consumer_blob()

    print("=" * 72)
    print("СЛЕД ВЫРЕЗАННЫХ МЕХАНИК — кандидаты, не приговор")
    print("=" * 72)

    candidates, service = routes_without_consumer(blob)
    print(f"\n[1] Маршруты без потребителя — КАНДИДАТЫ: {len(candidates)}")
    print("    (подключены к приложению, но не упоминаются ни во фронте,")
    print("     ни в шаблонах, ни в модах — и не выглядят служебными)")
    for rel, line, method, path in candidates:
        print(f"    {method:6} {path:55} {rel}:{line}")

    print(f"\n[1-бис] Служебные без потребителя: {len(service)}")
    print("    (вебхуки, Module API, админка, дашборд, оверлей — их зовёт не")
    print("     панель зрителя; отсутствие во фронте нормально)")
    for rel, line, method, path in service:
        print(f"    {method:6} {path:55} {rel}:{line}")

    orphans = frontend_files_not_included()
    print(f"\n[2] Файлы фронта, не подключённые ни в одном шелле: {len(orphans)}")
    for o in orphans:
        print(f"    {o}")

    tables = tables_without_users()
    print(f"\n[3] Таблицы без обращений вне миграций: {len(tables)}")
    for t in tables:
        print(f"    {t}")

    consts = config_constants_without_users()
    print(f"\n[4] Константы конфига без потребителей: {len(consts)}")
    for c in consts:
        print(f"    {c}")

    print("\n" + "=" * 72)
    print("Разбирать сверху вниз: маршрут без потребителя, который ещё и"
          " списывает\nкрустики, — это задняя дверь, а не мёртвый код.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
