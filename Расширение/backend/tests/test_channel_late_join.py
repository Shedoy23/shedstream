"""
test_channel_late_join.py — бот заходит в чат канала, одобренного после старта.

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_channel_late_join.py

ЗАЧЕМ. До 2026-08-22 `TwitchChatBot` джойнил чаты ОДИН раз, на старте бэкенда.
Новый стример регистрировался и одобрялся — а бот не приходил к нему до
перезапуска процесса. Со стороны новичка это не «подождите», а «ничего не
работает»: расширение стоит, чат молчит. Для онбординга незнакомого человека
это блокер, и в коде он был честно помечен как «Late-join — TODO future».

Проверяем ЧИСТУЮ функцию решения `channels_to_join` — она отвечает на
единственный вопрос, в котором можно ошибиться: кого дозаходить. Сам вызов
twitchio поверх неё — три строки, и их проверит живой прогон.
"""
from __future__ import annotations

import os
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
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("TWITCH_OAUTH_TOKEN", "oauth:test")
os.environ.setdefault("TWITCH_CLIENT_ID", "test_client")
os.environ.setdefault("TWITCH_CLIENT_SECRET", "test_secret")
os.environ.setdefault("TWITCH_BOT_ID", "test_bot")
os.environ.setdefault("TWITCH_EXTENSION_SECRET", "test-ext-secret-32bytes-1234567890ab")
os.environ.setdefault("MODULE_TOKEN_SECRET", "test-module-secret-32bytes-1234567890")
os.environ.setdefault("ADMIN_PASSWORD", "test_admin_password_for_tests_only")

_failures: list = []


def check(cond: bool, label: str):
    if cond:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label}")
        _failures.append(label)


def main() -> int:
    from main import channels_to_join

    print("\n[1] Новый канал появился после старта")
    got = channels_to_join(["shedoy23", "newcomer"], ["shedoy23"])
    check(got == ["newcomer"], f"дозаходим только к новому (получено: {got})")

    print("\n[2] Повторно в тот же чат не ломимся")
    # Цикл сверки крутится раз в минуту. Без этого бот слал бы JOIN на каждом
    # тике — Twitch считает это флудом и отключает соединение.
    got = channels_to_join(["shedoy23"], ["shedoy23"])
    check(got == [], f"когда все на месте — не заходим никуда (получено: {got})")

    print("\n[3] Регистр и решётка не создают дублей")
    # В реестре логины хранятся как есть, twitchio отдаёт свои, а Twitch к
    # регистру безразличен. Без нормализации 'Shedoy23' выглядел бы новым
    # каналом каждую минуту.
    got = channels_to_join(["Shedoy23", "#NewComer"], ["shedoy23"])
    check(got == ["newcomer"], f"'Shedoy23' не считается новым (получено: {got})")

    print("\n[3-бис] …и с той стороны, откуда приходит twitchio")
    # Нормализовать надо ОБА списка. Первая редакция этого теста держала
    # «где сидим» всегда в нижнем регистре и потому не замечала, если
    # нормализацию оттуда убрать: бот заходил бы в тот же чат каждую минуту.
    # Нашлось обязательным прогоном «красным».
    got = channels_to_join(["shedoy23"], ["Shedoy23"])
    check(got == [], f"канал в другом регистре опознан как уже join'нутый (получено: {got})")
    got = channels_to_join(["shedoy23"], ["#shedoy23"])
    check(got == [], f"решётка в имени канала не создаёт повторный JOIN (получено: {got})")

    print("\n[4] Дубли внутри реестра схлопываются")
    got = channels_to_join(["newcomer", "NewComer", "newcomer"], [])
    check(got == ["newcomer"], f"один JOIN на канал (получено: {got})")

    print("\n[5] Мусор не превращается в канал")
    got = channels_to_join(["", None, "  ", "newcomer"], [])
    check(got == ["newcomer"], f"пустые значения отброшены (получено: {got})")

    print("\n[6] Пустой реестр — не повод паниковать")
    check(channels_to_join([], ["shedoy23"]) == [], "пустой реестр даёт пустой список")
    check(channels_to_join(None, None) == [], "None вместо списков не роняет")

    print("\n" + "=" * 58)
    if _failures:
        print(f"ПРОВАЛЕНО: {len(_failures)}")
        for f in _failures:
            print("  -", f)
        return 1
    print("Все проверки прошли")
    return 0


if __name__ == "__main__":
    sys.exit(main())
