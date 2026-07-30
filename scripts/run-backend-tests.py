# -*- coding: utf-8 -*-
"""run-backend-tests.py — прогнать ВСЕ standalone-тесты бэкенда и судить по коду
возврата.

    python scripts/run-backend-tests.py            # все
    python scripts/run-backend-tests.py rimworld   # только совпавшие по имени

ЗАЧЕМ (2026-07-30). Тесты здесь — обычные скрипты, а не pytest, и запускать их
приходилось по одному. При полном прогоне вручную 30.07 восемь из них дали
exit=1, и это выглядело как восемь регрессий. На деле ни одна: на Windows
консоль в cp1251, `config.py` печатает предупреждение с эмодзи, печать падает
UnicodeEncodeError ещё на импорте — тест не начинался. С `PYTHONIOENCODING=utf-8`
все восемь зелёные. То есть восемь тестов на этом ПК не запускались вообще, и
никто этого не видел, потому что полного прогона не делал никто.

Поэтому здесь: единая кодировка, таймаут (висящий тест = провал, а не «ждём»),
и вердикт по КОДУ ВОЗВРАТА, а не по напечатанному «OK» (CLAUDE.md §2c).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent.parent / "Расширение" / "backend" / "tests"
TIMEOUT_SEC = 300

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def main() -> int:
    needle = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    files = sorted(p for p in TESTS_DIR.glob("test_*.py")
                   if needle in p.name.lower())
    if not files:
        print(f"Нет тестов по фильтру '{needle}'")
        return 2

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    failed: list[tuple[str, int]] = []

    for path in files:
        try:
            proc = subprocess.run([sys.executable, f"tests/{path.name}"],
                                  cwd=str(TESTS_DIR.parent), env=env,
                                  capture_output=True, timeout=TIMEOUT_SEC)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            code = 124  # завис — это провал, а не «наверное, ок»
        mark = "OK  " if code == 0 else "FAIL"
        note = "  (таймаут)" if code == 124 else ""
        print(f"[{mark}] exit={code:<4} {path.name}{note}")
        if code != 0:
            failed.append((path.name, code))

    print("-" * 60)
    if failed:
        print(f"ПРОВАЛЕНО {len(failed)} из {len(files)}:")
        for name, code in failed:
            print(f"  {name} (exit={code})")
        print("Вывод провалившегося: python tests/<имя>.py")
        return 1
    print(f"ВСЕ ЗЕЛЁНЫЕ: {len(files)} тестов, exit 0 у каждого")
    return 0


if __name__ == "__main__":
    sys.exit(main())
