"""
test_odds_disclosure.py — раскрытые шансы совпадают с настоящими весами.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_odds_disclosure.py

## Зачем

Расширение показывает ревьюеру Twitch и зрителю проценты выпадения тиров.
Это compliance-текст (§5.3): раскрытие, которое разошлось с кодом, хуже
отсутствующего — оно вводит в заблуждение.

Разойтись легко: 05.09 добавили ежечасную раздачу кейсов с весами 69/25/6/0.1,
а блок раскрытия остался с прежними 70/25/4/1 — то есть панель заявляла
неверные вероятности для новой механики. Нашёл внешний обзор.

## Чего требуем

1. Для каждого источника случайного тира в панели есть свой список процентов.
2. Проценты совпадают с весами из конфигурации (с точностью до 0.05 п.п.).
3. Оболочки extension.html и mobile.html содержат одно и то же.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

HERE = Path(__file__).parent.absolute()
BACKEND = HERE.parent
FRONTEND = BACKEND.parent / "frontend"
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


def _percent_lists(html: str) -> list[dict]:
    """Все списки <ul> с процентами по тирам, в порядке появления."""
    out = []
    for block in re.findall(r"<ul[^>]*>(.*?)</ul>", html, re.S):
        rows = re.findall(r"<li>\s*(Common|Rare|Epic|Legendary)\s*—\s*([\d.]+)%", block)
        if rows:
            out.append({tier.lower(): float(value) for tier, value in rows})
    return out


def _expected(weights) -> dict:
    total = sum(w for _, w in weights)
    return {tier: round(w * 100.0 / total, 2) for tier, w in weights}


def main() -> int:
    from config import HOURLY_CASE_TIERS
    from bot_core import DROP_CASE_TIERS

    html = (FRONTEND / "extension.html").read_text(encoding="utf-8")
    mobile = (FRONTEND / "mobile.html").read_text(encoding="utf-8")

    lists = _percent_lists(html)
    check("в панели два списка процентов — по одному на источник",
          len(lists) == 2, f"найдено {len(lists)}")
    if len(lists) != 2:
        return 1

    for name, weights, shown in (
        ("дроп", DROP_CASE_TIERS, lists[0]),
        ("часовой кейс", HOURLY_CASE_TIERS, lists[1]),
    ):
        expected = _expected(weights)
        bad = [f"{t}: показано {shown.get(t)}%, на деле {expected[t]}%"
               for t in expected
               if abs(shown.get(t, -1) - expected[t]) > 0.05]
        check(f"{name}: проценты совпадают с весами", not bad, "; ".join(bad))

    check("оболочки раскрывают одно и то же",
          _percent_lists(mobile) == lists, "extension.html и mobile.html разошлись")

    print()
    if fails:
        print(f"ПРОВАЛЕНО: {len(fails)} — " + "; ".join(fails))
        return 1
    print("ВСЁ ЗЕЛЁНОЕ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
