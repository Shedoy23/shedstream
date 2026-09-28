"""
test_bannerlord_refusal_coverage.py — у каждого отказа мода есть человеческая фраза.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_bannerlord_refusal_coverage.py

## Зачем

Мод отвечает кодом (`not_enough_gold`, `troop_maxed`, …). Если кода нет в
словаре, зритель видит общее «Игра отказала в этом действии» — то есть платит,
получает отказ и не понимает, что исправить. На 06.09 таких кодов было 31,
включая все денежные.

Тест не даёт долгу вернуться: новый код в моде без фразы в словаре = красный.
Это тот случай, когда проверку дешевле держать машиной, чем помнить.
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
ROOT = BACKEND.parent.parent
sys.path.insert(0, str(BACKEND))

for _k, _v in (
    ("TWITCH_OAUTH_TOKEN", "oauth:test"), ("TWITCH_CLIENT_ID", "test_client"),
    ("TWITCH_CLIENT_SECRET", "test_secret"), ("TWITCH_BOT_ID", "test_bot"),
    ("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab"),
    ("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890"),
    ("ADMIN_PASSWORD", "test_admin_password_for_tests_only"),
):
    os.environ.setdefault(_k, _v)

from modules.bannerlord.refusals import _FALLBACK, describe   # noqa: E402

# Коды бывают динамическими: PostFailed(id, "skill_cap_reached:" + skill).
# Двоеточие обязательно захватываем — иначе именно денежные отказы
# (они как раз такие) проходят мимо проверки, как прошли 06.09.
_CODE = re.compile(r'PostFailed\(\s*[A-Za-z_.]+\s*,\s*"([a-z0-9_]+):?"', re.I)


def main() -> int:
    mod_src = ROOT / "BannerlordLink" / "src"
    if not mod_src.is_dir():
        print("  SKIP  исходников мода нет рядом — проверять нечего")
        return 0

    codes = set()
    for path in mod_src.rglob("*.cs"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        codes.update(m.group(1) for m in _CODE.finditer(text))

    uncovered = sorted(c for c in codes if describe(c) == _FALLBACK)
    print(f"  кодов отказа в моде: {len(codes)}")
    print(f"  без своей фразы:     {len(uncovered)}")

    # Денежные проверяем поимённо: именно они означают «заплатил и не понял».
    money = ["not_enough_gold", "gold_not_applied", "troop_maxed", "peace_no_effect"]
    bad_money = [c for c in money if describe(c) == _FALLBACK]
    if bad_money:
        print("  FAIL денежные отказы без объяснения: " + ", ".join(bad_money))
        return 1
    print("  OK   денежные отказы объяснены")

    if uncovered:
        print("  FAIL коды без фразы (добавь в modules/bannerlord/refusals.py):")
        for c in uncovered:
            print("        ", c)
        return 1
    print("  OK   у каждого кода мода есть фраза")

    # И обратная защита: fallback обязан остаться на месте для чужих кодов.
    if describe("совсем_новый_код_из_будущего") != _FALLBACK:
        print("  FAIL неизвестный код должен давать общую фразу, а не пустоту")
        return 1
    print("  OK   неизвестный код даёт честную общую фразу")

    print("\nВСЁ ЗЕЛЁНОЕ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
