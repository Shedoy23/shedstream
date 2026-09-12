# -*- coding: utf-8 -*-
"""check-published-artifacts.py — манифест против того, что реально лежит на сервере.

    python scripts/check-published-artifacts.py            # все манифесты
    python scripts/check-published-artifacts.py rimworld   # только совпавшие по имени

ЗАЧЕМ (2026-09-12). Менеджер ставит мод так: читает манифест, качает архив по
ссылке и ОТКАЗЫВАЕТСЯ его ставить, если размер или SHA-256 не совпали с
манифестом (`ArtifactVerifier.Verify`, сообщение «Artifact size does not match
the manifest»). Манифесты 0.1.3/0.1.4 были сделаны копией предыдущих: ссылку и
SHA-256 обновили, а `size_bytes` остался от старой версии — байт в байт. То
есть установка ТРЁХ актуальных модов падала у любого, кто её запускал, и
узнать об этом можно было только запустив менеджер.

Схемная проверка этого не ловит и не может: она не знает, что лежит на
сервере. Поэтому здесь единственная проверка, которая ходит в сеть, — и она
отвечает на вопрос «а установится ли то, что мы выпустили».

ВЕРДИКТ ПО КОДУ ВОЗВРАТА: 0 — всё сходится; 1 — есть расхождение; 2 — не
удалось проверить (сеть, 404). «Не удалось» это НЕ «ок»: 2 отличается от 0
намеренно.
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFESTS = ROOT / "manifests" / "installation"
TIMEOUT_SEC = 120

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=TIMEOUT_SEC) as resp:
        return resp.read()


def main() -> int:
    needle = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    files = sorted(p for p in MANIFESTS.glob("*.json")
                   if "schema" not in p.name and needle in p.name.lower())
    if not files:
        print(f"Нет манифестов по фильтру '{needle}'")
        return 2

    mismatched: list[str] = []
    unchecked: list[str] = []
    for path in files:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for artifact in manifest.get("artifacts") or []:
            url = (artifact.get("source") or {}).get("url")
            if not url:
                continue
            try:
                blob = fetch(url)
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                unchecked.append(f"{path.name}: {url} — {type(exc).__name__}: {exc}")
                print(f"[??] {path.name}: не скачался — {exc}")
                continue
            size_ok = len(blob) == artifact.get("size_bytes")
            sha = hashlib.sha256(blob).hexdigest()
            sha_ok = sha == artifact.get("sha256")
            if size_ok and sha_ok:
                print(f"[OK] {path.name}: {len(blob)} байт, sha256 сошёлся")
                continue
            if not size_ok:
                mismatched.append(
                    f"{path.name}: size_bytes={artifact.get('size_bytes')}, "
                    f"а на сервере {len(blob)} — менеджер откажется ставить этот мод")
            if not sha_ok:
                mismatched.append(
                    f"{path.name}: sha256 манифеста {str(artifact.get('sha256'))[:16]}…, "
                    f"а у файла {sha[:16]}… — опубликован не тот архив")
            print(f"[!!] {path.name}: расхождение")

    print("-" * 60)
    for line in mismatched:
        print(f"  РАСХОЖДЕНИЕ {line}")
    for line in unchecked:
        print(f"  НЕ ПРОВЕРЕНО {line}")
    if mismatched:
        print(f"ПРОВАЛЕНО: {len(mismatched)} расхождений в {len(files)} манифестах")
        return 1
    if unchecked:
        print(f"НЕ ПРОВЕРЕНО: {len(unchecked)} артефактов — это не «ок»")
        return 2
    print(f"ВСЁ СОШЛОСЬ: {len(files)} манифестов, каждый ставится тем, что лежит на сервере")
    return 0


if __name__ == "__main__":
    sys.exit(main())
