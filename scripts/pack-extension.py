# -*- coding: utf-8 -*-
"""pack-extension.py — собрать версию расширения для загрузки в кабинет Twitch.

ЗАЧЕМ. Twitch принимает фронт архивом, который вручную загружают в кабинет
разработчика. Пока это делалось на глаз: какие файлы класть, что не забыть,
какая версия внутри — всё держалось в голове. Отсюда классическая ошибка
«загрузил не то» или «в архиве старый файл», причём заметить это можно только
после публикации, а откат у Twitch долгий.

Скрипт кладёт в архив ровно то, что нужно расширению, проставляет номер версии
видимой строкой в оба шелла и печатает список файлов для сверки глазами.

ЗАПУСК:
    python scripts/pack-extension.py --version 0.0.2
    python scripts/pack-extension.py --version 0.0.2 --check   # только проверить

Архив кладётся в `dist/` (вне git). Для обновления после первого релиза:
создать новую версию в кабинете, пройти Local Test, загрузить неизменяемый ZIP,
проверить его в Hosted Test и отправить на Review. Полный порядок:
`Расширение/docs/TWITCH_UPDATE_RELEASE_PLAYBOOK.md`.

НЕ ДЕПЛОИТ никуда. Только собирает файл, который ты загружаешь руками.
"""
import argparse
import io
import json
import os
import pathlib
import re
import sys
import zipfile
from datetime import datetime, timezone

# Вывод скрипта — русский с рамками. Консоль Windows по умолчанию cp1251, и
# первая же строка «═══ состав версии ═══» роняла скрипт с UnicodeEncodeError
# ещё до сборки архива (2026-08-05). Печать переводим в UTF-8 явно, иначе
# запуск из PowerShell не работает вообще.
for _stream in ("stdout", "stderr"):
    try:
        getattr(sys, _stream).reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO = pathlib.Path(__file__).resolve().parent.parent
EXT = next((p for p in REPO.iterdir() if (p / "backend").is_dir()), None)
FRONT = EXT / "frontend" if EXT else None
DIST = REPO / "dist"

# Что уходит в расширение. Список явный, а не «всё из папки»: в frontend/
# лежат и служебные файлы (страница стримера, приватность), которые Twitch
# не нужны, а лишний вес замедляет загрузку у каждого зрителя.
SHELLS = ["extension.html", "mobile.html", "config.html"]

# `overlay.html` СЮДА НЕ ВОЗВРАЩАТЬ. У нас это виджет для OBS, который стример
# добавляет источником браузера, а НЕ Twitch video-overlay: тип расширения —
# видео-расширение (`extension.html` + `mobile.html`), путь оверлея в консоли
# Twitch не наш. Класть его в архив — отдавать ревьюеру 60 КБ кода, который
# расширение не исполняет, и повод для вопросов на ровном месте.
# Правило: `Расширение/docs/TWITCH_UPDATE_RELEASE_PLAYBOOK.md`, пункт 4-тер.
# История: скрипт написан 27.07 и клал оверлей; правило найдено при сверке с
# докой Twitch 29.07 (`48e60b3`) и до кода не доехало — архив от 27.07 лишний
# файл содержал. Убрано 01.08.
EXTRA_HTML = []


def collect_scripts(shell: pathlib.Path) -> list:
    """Скрипты и стили, на которые ссылается шелл — в порядке подключения."""
    html = shell.read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r'(?:src|href)="([^"?]+\.(?:js|css))(?:\?[^"]*)?"', html):
        ref = m.group(1)
        if ref.startswith(("http://", "https://", "//")):
            continue          # внешние (шрифты) — не наши, не пакуем
        out.append(ref.lstrip("./"))
    return out


def stamp_version(text: str, version: str) -> str:
    """Проставить видимую строку версии в <head>.

    Видимая — намеренно: открыв исходник загруженной версии, можно за секунду
    понять, ЧТО именно сейчас крутится у зрителей. Без этого отличить сборки
    можно только по косвенным признакам.
    """
    marker = '<meta name="shedlink-version" content="%s">' % version

    # Разметку НЕ правим — только вставляем строку. Прежние две попытки чинили
    # это иначе и обе оказались хуже: голый re.sub по всему файлу выедал
    # упоминание тега из HTML-комментария («Заполняется из
    # <meta name="shedlink-version"> — метку ставит…»), а его аккуратная версия
    # всё ещё срабатывала, если тег в комментарии стоял отдельной строкой, —
    # и затвор этого не видел, потому что применял ту же чистку к эталону.
    # Вывод простой: пока функция что-то удаляет, проверять её нечем.
    #
    # Метку в рабочем дереве держать не нужно вообще: её ставит сборка. Поэтому
    # вместо удаления — отказ: настоящий тег в исходнике значит, что кто-то
    # закоммитил метку, и это надо чинить в дереве, а не молча затирать здесь.
    # Комментарии из проверки исключаем, они рассказывают о теге, а не задают его.
    if 'name="shedlink-version"' in re.sub(r"<!--.*?-->", "", text, flags=re.S):
        raise SystemExit(
            "В исходнике уже стоит тег версии — убери его из frontend/: метку "
            "проставляет сборка, в рабочем дереве её быть не должно.")

    # Перевод строки берём такой же, как в файле: config.html хранится с CRLF,
    # и вставка с голым \n оставляла в нём одну строку с чужим окончанием.
    eol = "\r\n" if "\r\n" in text else "\n"
    head = text.find("<head>")
    if head < 0:
        raise SystemExit("В шелле нет <head> — некуда ставить метку версии.")
    at = head + len("<head>")
    line = eol + "  " + marker
    stamped = text[:at] + line + text[at:]

    # Затвор: вырезаем ровно то, что вставили (по позиции, не поиском), и
    # результат обязан совпасть с ОРИГИНАЛОМ буква в букву. Никакой
    # нормализации — именно она делала обе прошлые проверки слепыми.
    # Гейт живёт в самой сборке: она запускается всегда, а отдельный тест — когда вспомнят.
    if stamped[:at] + stamped[at + len(line):] != text:
        raise SystemExit(
            "Штамповка версии изменила файл сверх вставленной строки — сборка "
            "остановлена. Проверь stamp_version().")
    return stamped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True,
                    help="номер версии, например 0.0.2")
    ap.add_argument("--check", action="store_true",
                    help="только проверить состав, архив не создавать")
    args = ap.parse_args()

    if FRONT is None or not FRONT.is_dir():
        print("Не нашёл папку frontend — запускай из репозитория.")
        return 1
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        print("Версия должна быть вида 0.0.2")
        return 1

    files, missing = [], []
    for shell in SHELLS + EXTRA_HTML:
        p = FRONT / shell
        if not p.exists():
            missing.append(shell)
            continue
        files.append(shell)
        for ref in collect_scripts(p):
            if (FRONT / ref).exists():
                if ref not in files:
                    files.append(ref)
            else:
                missing.append("%s (нужен для %s)" % (ref, shell))

    print("═══ состав версии %s ═══" % args.version)
    total = 0
    for f in files:
        size = (FRONT / f).stat().st_size
        total += size
        print("  %-30s %7.1f КБ" % (f, size / 1024))
    print("  %-30s %7.1f КБ  (%d файлов)" % ("ИТОГО", total / 1024, len(files)))

    if missing:
        print("\nНЕ НАЙДЕНО (архив собирать нельзя):")
        for m in missing:
            print("   ", m)
        return 1

    if args.check:
        print("\n(--check: архив не создавался)")
        return 0

    DIST.mkdir(exist_ok=True)
    out = DIST / ("shedlink-%s.zip" % args.version)
    # Пишем во временный файл и переименовываем в конце. Иначе падение посреди
    # сборки (например, затвор штамповки) оставляет на месте архива огрызок в
    # 22 байта — а его потом можно по ошибке залить в кабинет.
    tmp = out.with_suffix(".zip.part")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for f in files:
                data = (FRONT / f).read_bytes()
                if f.endswith(".html"):
                    data = stamp_version(
                        data.decode("utf-8"), args.version).encode("utf-8")
                z.writestr(f, data)
            z.writestr("VERSION", "%s\nсобрано %s\n" % (
                args.version, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")))
    except BaseException:
        tmp.unlink(missing_ok=True)     # не оставляем недособранный кусок рядом с архивом
        raise
    os.replace(tmp, out)

    print("\nГотово: %s (%.1f КБ)" % (out, out.stat().st_size / 1024))
    print("\nЧто дальше — ВРУЧНУЮ:")
    print("  1. Кабинет разработчика Twitch → Extensions → ShedLink")
    print("  2. Создать новую версию %s" % args.version)
    print("  3. Пройти Local Test и сверить настройки версии")
    print("  4. Загрузить этот архив в Version Assets")
    print("  5. Прогнать именно его в Hosted Test")
    print("  6. Submit for Review; после Approved владелец отдельно нажимает Release")
    print("  Регламент: Расширение/docs/TWITCH_UPDATE_RELEASE_PLAYBOOK.md")
    print("\nСкрипт сам НИЧЕГО не публикует.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
