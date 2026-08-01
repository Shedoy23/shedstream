"""
test_module_secret_failclosed.py — REGRESSION-тест на дыру S-15
(внешний аудит 2026-07-27, подтверждена по коду 2026-08-01).

Standalone (без pytest). Запуск:
    cd Расширение/backend
    python tests/test_module_secret_failclosed.py

## Что за дыра

`issue_module_token` / `verify_module_token` / `issue_overlay_token` подписывали
HMAC ключом `MODULE_TOKEN_SECRET`, а при пустом секрете молча падали на
константу `unconfigured-module-secret`:

    secret = (MODULE_TOKEN_SECRET or "").encode() or b"unconfigured-module-secret"

Строка лежит в исходниках и в опубликованном отчёте внешнего аудита. Значит на
деплое с пустым `.env` кто угодно мог собрать валидный module-token за ЧУЖОЙ
канал и говорить с Module API от имени его мода: читать и подтверждать очередь
платных действий, слать события. Тем же ключом подделывался overlay-токен,
которым защищено гашение платной озвучки.

На нынешнем проде оба секрета заданы (проверено 2026-08-01), то есть дыра
СПАЛА, а не эксплуатировалась. Опасность в том, что код сам себя не защищал:
пустой `.env` после переноса или неудачного деплоя открывал дверь молча.

## Как чинится

`_module_secret()` вместо фолбэка бросает `ModuleSecretMissing`. Пути проверки
(`verify_module_token`, `verify_overlay_token`) ловят и отвечают «нет» — то есть
отклоняют ВСЕ токены и пишут ошибку в лог. Пути выдачи падают громко.
Принцип: лучше «не работает и видно», чем «работает и открыто всем».

## Тест видели красным (правило CLAUDE.md 2b)

До фикса:
    ❌ токен, подделанный публичной константой, отвергнут: expected None, got {...}
    ❌ overlay-токен, подделанный публичной константой, отвергнут: expected False, got True
После фикса — зелёное.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sys
import time
import traceback
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
os.environ.setdefault("TWITCH_BROADCASTER_ID", "98319857")

# Ровно та строка, что лежала в коде как фолбэк и попала в отчёт аудита.
PUBLIC_FALLBACK = b"unconfigured-module-secret"
VICTIM_CHANNEL = 98319857

_failures: list = []
_successes: list = []


def assert_eq(actual, expected, label: str):
    if actual == expected:
        _successes.append(label)
        print(f"  ✅ {label}")
    else:
        msg = f"  ❌ {label}: expected {expected!r}, got {actual!r}"
        _failures.append(msg)
        print(msg)


def _forge_module_token(channel_id: int, module_id: str) -> str:
    """Собрать module-token, зная ТОЛЬКО публичную константу."""
    expires_at = int(time.time()) + 3600
    msg = f"{int(channel_id)}|{module_id}|{expires_at}"
    sig = hmac.new(PUBLIC_FALLBACK, msg.encode(), hashlib.sha256).hexdigest()
    return f"{msg}|{sig}"


def _forge_overlay_token(channel_id: int) -> str:
    msg = f"overlay|{int(channel_id)}"
    return hmac.new(PUBLIC_FALLBACK, msg.encode(), hashlib.sha256).hexdigest()[:32]


def test_forged_token_rejected_when_secret_empty():
    """Пустой секрет не должен превращаться в публично известный ключ."""
    print("\n[1] S-15: подделка токена при пустом MODULE_TOKEN_SECRET")

    import routes.streamer as streamer

    original = streamer.MODULE_TOKEN_SECRET
    streamer.MODULE_TOKEN_SECRET = ""      # деплой с пустым .env
    try:
        forged = _forge_module_token(VICTIM_CHANNEL, "bannerlord")
        assert_eq(streamer.verify_module_token(forged), None,
                  "токен, подделанный публичной константой, отвергнут")

        forged_overlay = _forge_overlay_token(VICTIM_CHANNEL)
        assert_eq(streamer.verify_overlay_token(VICTIM_CHANNEL, forged_overlay), False,
                  "overlay-токен, подделанный публичной константой, отвергнут")

        # Выдача при пустом секрете обязана падать громко, а не молча подписывать.
        try:
            streamer.issue_module_token(VICTIM_CHANNEL, "bannerlord")
            assert_eq("подписал молча", "отказ", "выдача токена при пустом секрете отказывает")
        except streamer.ModuleSecretMissing:
            assert_eq(True, True, "выдача токена при пустом секрете отказывает")
    finally:
        streamer.MODULE_TOKEN_SECRET = original


def test_normal_path_still_works():
    """С заданным секретом всё работает как раньше — фикс не сломал штатное."""
    print("\n[2] Штатная выдача и проверка не сломаны")

    import routes.streamer as streamer

    token = streamer.issue_module_token(VICTIM_CHANNEL, "bannerlord")
    claims = streamer.verify_module_token(token)
    assert_eq(bool(claims), True, "свой токен проходит проверку")
    assert_eq(claims and claims.get("channel_id"), VICTIM_CHANNEL,
              "в токене тот самый канал")
    assert_eq(claims and claims.get("module_id"), "bannerlord",
              "в токене тот самый модуль")

    overlay = streamer.issue_overlay_token(VICTIM_CHANNEL)
    assert_eq(streamer.verify_overlay_token(VICTIM_CHANNEL, overlay), True,
              "свой overlay-токен проходит проверку")
    assert_eq(streamer.verify_overlay_token(VICTIM_CHANNEL + 1, overlay), False,
              "overlay-токен чужого канала не проходит")


def main():
    print("=" * 70)
    print("REGRESSION S-15: пустой секрет = отказ, а не публичный ключ")
    print("=" * 70)
    try:
        test_forged_token_rejected_when_secret_empty()
        test_normal_path_still_works()
    except Exception:
        print("\n💥 Test harness CRASHED (не assertion — инфраструктура):")
        traceback.print_exc()
        sys.exit(2)

    print("\n" + "=" * 70)
    print(f"PASSED: {len(_successes)}   FAILED: {len(_failures)}")
    if _failures:
        print("\nFAILURES:")
        for f in _failures:
            print(f)
        sys.exit(1)
    print("ALL GREEN ✅ — пустой секрет закрывает дверь, а не открывает.")
    sys.exit(0)


if __name__ == "__main__":
    main()
