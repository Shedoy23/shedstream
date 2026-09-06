"""
test_modded_keys_pass.py — бэкенд не решает, что существует в игре.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_modded_keys_pass.py

## Зачем

Выбранный принцип: источник истины о содержимом — запущенная игра (ROADMAP,
«динамический каталог»). До 2026-09-06 бэкенд держал белые списки ALLOWED_SKILLS
и ALLOWED_ATTRIBUTES: сборка, добавившая свой навык, получала отказ ещё на
сервере, хотя навык в игре есть и мод его знает.

Убрать проверку целиком тоже нельзя — иначе в игру уедет любая строка. Поэтому
бэкенд проверяет ФОРМАТ, а существование оставляет игре: не нашла — отказ с
возвратом и понятной фразой.

## Чего требуем

1. Модовый навык и модовая характеристика проходят серверную валидацию.
2. Ванильные проходят.
3. Мусор (пусто-подобные символы, пробелы, инъекции, слишком длинное) —
   отклоняется до того, как уедет в игру.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

HERE = Path(__file__).parent.absolute()
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))

for _k, _v in (
    ("TWITCH_OAUTH_TOKEN", "oauth:test"), ("TWITCH_CLIENT_ID", "test_client"),
    ("TWITCH_CLIENT_SECRET", "test_secret"), ("TWITCH_BOT_ID", "test_bot"),
    ("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab"),
    ("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890"),
    ("ADMIN_PASSWORD", "test_admin_password_for_tests_only"),
):
    os.environ.setdefault(_k, _v)

fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  OK   " if ok else "  FAIL ") + name + ("" if ok else " — " + detail))
    if not ok:
        fails.append(name)


def main() -> int:
    from routes.bannerlord import _GAME_KEY_RE, KNOWN_ATTRIBUTES, KNOWN_SKILLS

    ok = lambda key: bool(_GAME_KEY_RE.match(key))

    check("ванильный навык проходит", ok("OneHanded"))
    check("модовый навык проходит", ok("Wolfein_Gunnery"),
          "сборка вправе добавить свой навык — решать игре, не серверу")
    check("модовая характеристика проходит", ok("Samurai_Honor"))
    check("навык с цифрами проходит", ok("Skill2"))

    for bad, why in (
        ("", "пусто"),
        ("   ", "пробелы"),
        ("One Handed", "пробел внутри"),
        ("Skill;DROP", "точка с запятой"),
        ("../etc/passwd", "путь"),
        ("Ω" * 10, "не латиница"),
        ("A" * 49, "длиннее 48"),
    ):
        check(f"мусор отклонён ({why})", not ok(bad), repr(bad))

    check("списки известных значений остались как подсказка",
          "OneHanded" in KNOWN_SKILLS and "Vigor" in KNOWN_ATTRIBUTES)

    print()
    if fails:
        print(f"ПРОВАЛЕНО: {len(fails)} — " + "; ".join(fails))
        return 1
    print("ВСЁ ЗЕЛЁНОЕ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
