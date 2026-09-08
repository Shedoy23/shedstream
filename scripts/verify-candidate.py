#!/usr/bin/env python3
"""Кандидат в Twitch Review сверяется с кодом, а не с именем файла.

ЗАЧЕМ. За два дня один и тот же класс сработал дважды: в журнале стоял
«действующий кандидат», а код уже уехал вперёд.

  * 07.09 — план называл действующим `9200f6c2…`, отменённый в тот же день;
  * 08.09 — кандидат `6803b31e…` записан коммитом `6be92da`, следом пришёл
    `f8a27e9` и поменял пять JS-файлов; в архиве остались старые.

Номер версии при этом не менялся ни разу: пять разных байтовых наборов носили
имя `shedlink-0.0.5.zip`. Отличить их можно было только хешем, а хеш никто не
пересчитывал — потому что «версия та же».

Вторая половина того же класса — метка кэша. 09.09 архив и дерево несли
одинаковый `?v=202609081801` при разном содержимом JS: тот же адрес, другие
байты. Зритель с открытой панелью остался бы на старом коде, и это не видно
ни по номеру версии, ни по размеру архива.

ЧТО ПРОВЕРЯЕТСЯ

  1. Архив совпадает с рабочим деревом. Оболочкам разрешено отличаться ровно
     одной вставленной строкой `<meta name="shedlink-version">` — проверяем
     позиционно (вырезаем то, что вставлено, и требуем совпадения буква в
     букву), а не поиском подстроки: поиск уже однажды сделал проверку слепой.
  2. Метка кэша внутри архива одна и та же в обеих оболочках.
  3. Свежая запись журнала называет ИМЕННО этот архив: sha256, md5 и размер.
  4. Если свежая запись описывает другой архив, чем предыдущая, то и метка
     кэша обязана отличаться. Равные метки при разных байтах — тот самый
     «тот же ?v= на другом коде».

ГДЕ ЗАПУСКАТЬ. Перед тем как назвать кандидата в документах и перед загрузкой
в Dev Console. НЕ в pre-commit и не в основном прогоне CI: сразу после любой
правки фронта архив закономерно отстаёт, и блокирующая проверка была бы
красной каждый день — такие отключают. Мягкое напоминание об отставании живёт
в `lint_consistency.py` (`check_release_candidate_fresh`) как warning.

    python scripts/verify-candidate.py                 # версия из журнала
    python scripts/verify-candidate.py --version 0.0.5
    python scripts/verify-candidate.py --archive путь/к.zip
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONT = ROOT / "Расширение" / "frontend"
RECORD = ROOT / "Расширение" / "docs" / "RELEASE_RECORD.md"
DIST = ROOT / "dist"

SHELLS = ("extension.html", "mobile.html", "config.html")
STAMP_RE = re.compile(r'<meta name="shedlink-version" content="[^"]*">')
CACHE_RE = re.compile(r"\?v=(\d+)")
SHA_RE = re.compile(r"\b([0-9a-f]{64})\b")
MD5_RE = re.compile(r"\b([0-9a-f]{32})\b")

errors: list[str] = []
notes: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def strip_stamp(archive_text: str) -> tuple[str, int]:
    """Убрать вставленную сборкой строку версии — позиционно.

    Возвращает (текст_без_метки, сколько_меток_найдено). Комментарии не
    трогаем: тег внутри `<!-- ... -->` рассказывает о метке, а не задаёт её,
    и прошлая проверка спотыкалась именно об это.
    """
    without_comments = re.sub(r"<!--.*?-->", "", archive_text, flags=re.S)
    found = len(STAMP_RE.findall(without_comments))
    if found != 1:
        return archive_text, found
    m = STAMP_RE.search(archive_text)
    start, end = m.span()
    # Метка вставляется как EOL + два пробела + тег. Срезаем и её отступ.
    lead = start
    while lead > 0 and archive_text[lead - 1] == " ":
        lead -= 1
    if archive_text[:lead].endswith("\r\n"):
        lead -= 2
    elif archive_text[:lead].endswith("\n"):
        lead -= 1
    return archive_text[:lead] + archive_text[end:], 1


def check_archive_matches_tree(zf: zipfile.ZipFile) -> None:
    names = [i.filename for i in zf.infolist() if i.filename != "VERSION"]
    stale: list[str] = []
    for name in names:
        src = FRONT / name
        if not src.is_file():
            fail("в архиве есть %s, которого нет во frontend/" % name)
            continue
        packed = zf.read(name)
        tree = src.read_bytes()
        if packed == tree:
            continue
        if name not in SHELLS:
            stale.append(name)
            continue
        try:
            restored, found = strip_stamp(packed.decode("utf-8"))
        except UnicodeDecodeError:
            fail("%s в архиве не читается как UTF-8" % name)
            continue
        if found != 1:
            fail("%s: меток версии в архиве %d, ожидалась одна" % (name, found))
            continue
        if restored.encode("utf-8") != tree:
            stale.append(name)
    missing = sorted(
        p.name for p in FRONT.glob("*.js")
        if p.name not in names and p.name not in ("dice.js",)
    )
    if stale:
        fail("архив отстал от кода: %d файл(ов) не совпадают с деревом — %s. "
             "Пересобери (scripts/pack-extension.py) и обнови запись журнала."
             % (len(stale), ", ".join(sorted(stale))))
    else:
        notes.append("архив совпадает с деревом (%d файлов, оболочки — только метка версии)"
                     % len(names))
    if missing:
        notes.append("во frontend/ есть неупакованные .js: %s (норма, если они не "
                     "подключены в оболочках)" % ", ".join(missing))


def check_cache_bust(zf: zipfile.ZipFile) -> str | None:
    stamps: dict[str, set[str]] = {}
    for shell in ("extension.html", "mobile.html"):
        try:
            text = zf.read(shell).decode("utf-8")
        except KeyError:
            fail("в архиве нет %s" % shell)
            return None
        stamps[shell] = set(CACHE_RE.findall(text))
    if not stamps["extension.html"]:
        fail("в extension.html внутри архива нет ни одной метки кэша ?v=")
        return None
    if stamps["extension.html"] != stamps["mobile.html"]:
        fail("метка кэша разошлась между оболочками: extension=%s, mobile=%s — "
             "часть аудитории осталась бы на старом JS"
             % (sorted(stamps["extension.html"]), sorted(stamps["mobile.html"])))
        return None
    if len(stamps["extension.html"]) != 1:
        fail("в оболочках несколько разных меток кэша: %s"
             % sorted(stamps["extension.html"]))
        return None
    stamp = next(iter(stamps["extension.html"]))
    notes.append("метка кэша ?v=%s одинакова в обеих оболочках" % stamp)
    return stamp


def record_sections() -> list[str]:
    if not RECORD.is_file():
        fail("нет %s — журнал релизов пропал" % RECORD.name)
        return []
    text = RECORD.read_text(encoding="utf-8", errors="replace")
    return [s for s in re.split(r"\n## ", text)[1:]]


def check_cachebust_vs_previous(sha: str, stamp: str | None) -> None:
    """Метка кэша обязана меняться вместе с содержимым.

    Проверка НАМЕРЕННО не зависит от того, записан ли уже архив в журнал.
    Сначала она стояла внутри `check_record` после сверки sha — и на первом же
    прогоне выяснилось, что так она не срабатывает вообще: у незаписанного
    архива sha не совпадает, функция выходила раньше, и самый опасный случай
    («тот же ?v=, другие байты») проходил молча. Порядок работы обратный —
    сперва собирают и проверяют, потом записывают, — значит проверка обязана
    работать ДО записи.
    """
    if not stamp:
        return
    for sec in record_sections():
        shas = set(SHA_RE.findall(sec))
        if not shas or sha in shas:
            continue                      # это описание того же архива — не с чем сравнивать
        title = sec.splitlines()[0].strip()
        stamps = set(CACHE_RE.findall(sec)) | set(re.findall(r"\b(20\d{10})\b", sec))
        if stamp in stamps:
            fail("метка кэша ?v=%s та же, что у предыдущего кандидата («%s»), а архив "
                 "другой: один и тот же адрес отдавал бы разные байты, и зритель с "
                 "открытой панелью остался бы на старом JS. Обнови метку в обеих "
                 "оболочках и пересобери." % (stamp, title))
        else:
            notes.append("метка кэша отличается от предыдущего кандидата («%s»)" % title)
        return


def check_record(sha: str, md5: str, size: int) -> None:
    sections = record_sections()
    if not sections:
        return
    newest = sections[0]
    title = newest.splitlines()[0].strip()
    if sha not in SHA_RE.findall(newest):
        fail("свежая запись журнала («%s») не называет sha256 этого архива "
             "(%s…). Либо архив не записан, либо запись про другой." % (title, sha[:12]))
        return
    if md5 not in MD5_RE.findall(newest):
        fail("свежая запись журнала («%s») называет sha256 этого архива, но не "
             "его md5 (%s…) — в кабинете сверяют именно md5." % (title, md5[:12]))
    digits = re.sub(r"[^\d]", "", str(size))
    if digits not in re.sub(r"[   ]", "", newest):
        fail("свежая запись журнала («%s») не называет размер %d байт." % (title, size))
    notes.append("журнал: свежая запись «%s» описывает именно этот архив" % title)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", help="номер версии, например 0.0.5")
    ap.add_argument("--archive", help="путь к архиву (по умолчанию dist/shedlink-<версия>.zip)")
    args = ap.parse_args()

    if args.archive:
        path = Path(args.archive)
    else:
        version = args.version
        if not version:
            found = sorted(DIST.glob("shedlink-*.zip"))
            if len(found) != 1:
                print("Не понял, какой архив проверять: %s. Укажи --version или --archive."
                      % ([p.name for p in found] or "в dist/ архивов нет"))
                return 2
            path = found[0]
        else:
            path = DIST / ("shedlink-%s.zip" % version)
    if not path.is_file():
        print("Нет архива %s" % path)
        return 2

    blob = path.read_bytes()
    sha = hashlib.sha256(blob).hexdigest()
    md5 = hashlib.md5(blob).hexdigest()
    print("═══ кандидат %s ═══" % path.name)
    print("  размер : %d байт" % len(blob))
    print("  sha256 : %s" % sha)
    print("  md5    : %s" % md5)

    with zipfile.ZipFile(path) as zf:
        check_archive_matches_tree(zf)
        stamp = check_cache_bust(zf)
    check_cachebust_vs_previous(sha, stamp)
    check_record(sha, md5, len(blob))

    print()
    for n in notes:
        print("  OK   %s" % n)
    for e in errors:
        print("  FAIL %s" % e)
    if errors:
        print("\nПРОВАЛЕНО: %d. Этот архив называть кандидатом нельзя." % len(errors))
        return 1
    print("\nВСЁ ЗЕЛЁНОЕ: архив, метка кэша и журнал сходятся.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
