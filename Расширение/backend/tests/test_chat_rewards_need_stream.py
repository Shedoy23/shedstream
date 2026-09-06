"""
test_chat_rewards_need_stream.py — за чат платят только в эфире.

Standalone (без pytest):
    cd Расширение/backend
    python tests/test_chat_rewards_need_stream.py

## Зачем

В ночь на 2026-09-06 зритель писал в чат ровно раз в 11 минут при выключенном
стриме и закрыл два чат-квеста: 1700 крустиков и два кейса. Антифрод при этом
работал — он проверяет частоту (кулдаун 10с), длину и повторы, но не время
суток. Интервал в 11 минут проходит кулдаун с запасом, разный текст — дедуп.

Класс тот же, что и «свежий last_seen ≠ внимание»: сообщение в чате считалось
участием в эфире, хотя эфира не было.

## Чего требуем

1. Вне эфира чат не даёт ни бонуса, ни прогресса квестов.
2. В эфире всё работает как раньше.
3. Если статус стрима узнать не удалось — не платим (неизвестность не повод
   выдавать деньги).
4. Само сообщение вне эфира не теряется: статистика и пул голосования живут
   своей жизнью — писать в чат никто не запрещал.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

BACKEND = Path(__file__).resolve().parents[1]
fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  OK   " if ok else "  FAIL ") + name + ("" if ok else " — " + detail))
    if not ok:
        fails.append(name)


def main() -> int:
    src = (BACKEND / "main.py").read_text(encoding="utf-8")

    # Блок обработки сообщения: от антифрод-бонуса до чат-квестов.
    start = src.index("chat_stream_live") if "chat_stream_live" in src else -1
    check("статус эфира вообще выясняется", start >= 0,
          "в обработке чата нет обращения к _is_stream_live")
    if start < 0:
        return 1

    block = src[start:src.index("chat_messages_300")]

    check("бонус за сообщение зависит от эфира",
          re.search(r"compute_chat_bonus\([^)]*\)\s*if\s+chat_stream_live", block) is not None,
          "бонус считается независимо от статуса стрима")

    check("квесты не начисляются вне эфира",
          re.search(r"if\s+not\s+chat_stream_live:\s*\n\s*return", block) is not None,
          "прогресс квестов идёт без проверки эфира")

    check("неизвестный статус трактуется как «не платим»",
          re.search(r"except\s+Exception:\s*\n\s*chat_stream_live\s*=\s*False", block) is not None,
          "при ошибке проверки статус должен быть False, а не True")

    # Пул голосования и статистика не должны попасть под гейт — сообщение вне
    # эфира остаётся сообщением.
    pool_pos = src.index("increment_voting_pool")
    quest_gate_pos = src.index("if not chat_stream_live")
    check("пул голосования не отключён вместе с наградами",
          pool_pos < quest_gate_pos,
          "инкремент пула оказался за гейтом — сообщение вне эфира пропадёт целиком")

    print()
    if fails:
        print(f"ПРОВАЛЕНО: {len(fails)} — " + "; ".join(fails))
        return 1
    print("ВСЁ ЗЕЛЁНОЕ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
