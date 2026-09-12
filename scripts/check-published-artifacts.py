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
import re
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


def trusted_keys() -> dict:
    """Публичные ключи берём ИЗ КОДА МЕНЕДЖЕРА, а не из папки с ключами.

    Проверять надо тем же ключом, которым будет проверять пользователь: если
    подписать другим, гейт был бы зелёным, а установка падала бы «Artifact
    publisher key is invalid».
    """
    src = (ROOT / "ShedLink.Manager" / "src" / "ShedLink.Manager.App"
           / "ReleaseConfiguration.cs").read_text(encoding="utf-8")
    keys = {}
    for key_id, body in re.findall(
            r'\["([^"]+)"\]\s*=\s*"""(.*?)"""', src, re.S):
        pem = "\n".join(line.strip() for line in body.strip().splitlines())
        keys[key_id] = pem
    return keys


def signature_ok(manifest: dict, artifact: dict, blob: bytes) -> str:
    """Пусто — подпись сошлась; иначе текст расхождения.

    Payload обязан совпадать с ArtifactSignatureVerifier.SigningPayload:
    размер входит в подписываемые данные, поэтому правка size_bytes без
    переподписи ломает установку (так и вышло 12.09).
    """
    signature = artifact.get("signature") or {}
    key_id = signature.get("key_id")
    value = signature.get("value")
    if not value:
        return "артефакт без подписи, а источник https — менеджер такое не ставит"
    keys = trusted_keys()
    if key_id not in keys:
        return f"key_id={key_id!r} менеджеру неизвестен"
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        return ""  # без cryptography подпись не проверяем, об этом скажет сводка
    payload = ("ShedLink-Artifact-v1\n"
               f"{manifest['integration_id']}\n"
               f"{manifest['release_version']}\n"
               f"{artifact['id']}\n"
               f"{artifact['size_bytes']}\n"
               f"{artifact['sha256']}\n").encode("utf-8")
    public_key = serialization.load_pem_public_key(keys[key_id].encode("ascii"))
    import base64
    try:
        public_key.verify(
            base64.b64decode(value), payload,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256())
    except InvalidSignature:
        return ("подпись не сходится с (версия, размер, sha) — так бывает, когда "
                "манифест поправили руками и не переподписали")
    return ""


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
            sig_problem = signature_ok(manifest, artifact, blob) if size_ok and sha_ok else ""
            if size_ok and sha_ok and not sig_problem:
                print(f"[OK] {path.name}: {len(blob)} байт, sha256 и подпись сошлись")
                continue
            if sig_problem:
                mismatched.append(f"{path.name}: {sig_problem}")
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
